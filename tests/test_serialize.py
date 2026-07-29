"""Serialize a graph to Python source and round-trip it back."""

from __future__ import annotations

from typing import Any

import pytest

import serialize
from base import EntityInstance, Instance, Provenance
from example import Believes, Knows, Person, WorksFor, acme, alice, bob


def _by_id(instances: list[Instance]) -> dict[str, Instance]:
    return {i.id: i for i in instances}


def _roundtrip(instances: list[Instance]) -> list[Instance]:
    return serialize.from_python(serialize.to_python(instances))


def test_roundtrip_entities_and_statement() -> None:
    prov = Provenance(source="hr.csv", extraction_method="manual")
    wf = WorksFor(
        id="wf1",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov,),
    )
    got = _by_id(_roundtrip([wf]))
    assert got == _by_id([alice, acme, wf])
    rebuilt = got["wf1"]
    assert isinstance(rebuilt, WorksFor)
    assert rebuilt.provenance == wf.provenance


def test_roundtrip_statement_with_multiple_provenance_records() -> None:
    wf = WorksFor(
        id="wf1",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(
            Provenance(source="hr.csv", extraction_method="manual"),
            Provenance(source="wiki", extraction_method="model_extraction"),
        ),
    )
    got = _by_id(_roundtrip([wf]))
    rebuilt = got["wf1"]
    assert isinstance(rebuilt, WorksFor)
    assert rebuilt.provenance == wf.provenance


def test_closure_pulls_in_unlisted_dependencies() -> None:
    # Passing only the statement still emits its subject and object.
    wf = WorksFor(id="wf1", subject=alice, object_=acme)
    got = _by_id(_roundtrip([wf]))
    assert set(got) == {"alice", "acme", "wf1"}


def test_higher_order_roundtrip_preserves_concrete_type() -> None:
    wf = WorksFor(id="wf1", subject=alice, object_=acme, truth_status="asserted_true")
    outer = Believes(id="b1", subject=bob, object_=wf)
    got = _by_id(_roundtrip([outer]))
    assert got == _by_id([alice, acme, bob, wf, outer])
    rebuilt = got["b1"]
    assert isinstance(rebuilt, Believes)
    assert isinstance(rebuilt.object_, WorksFor)  # tau preserved through source


def test_shared_node_emitted_once() -> None:
    # alice is the subject of two statements; she should appear in one assignment.
    wf = WorksFor(id="wf1", subject=alice, object_=acme)
    knows = Knows(id="k1", subject=alice, object_=bob)
    src = serialize.to_python([wf, knows])
    assert src.count('Person(id="alice"') == 1


def test_shared_statement_node_emitted_once() -> None:
    # A statement reused as a higher-order object should still have one assignment.
    wf = WorksFor(id="wf1", subject=alice, object_=acme)
    believes_bob = Believes(id="b1", subject=bob, object_=wf)
    believes_alice = Believes(id="b2", subject=alice, object_=wf)
    src = serialize.to_python([believes_bob, believes_alice])
    assert src.count("wf1 = WorksFor(") == 1


def test_punctuated_id_is_sanitized_and_roundtrips() -> None:
    holmes = Person(id="wiki:Sherlock_Holmes", name="Sherlock Holmes")
    wf = WorksFor(id="w2", subject=holmes, object_=acme)
    got = _by_id(_roundtrip([wf]))
    assert (
        got["wiki:Sherlock_Holmes"] == holmes
    )  # source executed, so the name was valid


def test_output_is_self_contained_source() -> None:
    # The emitted program carries its own imports and executes on empty globals.
    src = serialize.to_python([WorksFor(id="wf1", subject=alice, object_=acme)])
    assert src.startswith(f"{serialize._GENERATED_HEADER}\n")
    ns: dict[str, Any] = {}
    exec(src, ns)  # must not raise


def test_inconsistent_duplicate_ids_raise() -> None:
    a1 = Person(id="dup", name="One")
    a2 = Person(id="dup", name="Two")
    with pytest.raises(ValueError, match="share id"):
        serialize.to_python([a1, a2])


def test_id_shadowing_imported_class_name_is_disambiguated() -> None:
    meta = Person(id="Person", name="Meta")
    q = Person(id="q", name="Q")
    src = serialize.to_python([meta, q])
    assert "Person = Person(" not in src
    got = _by_id(serialize.from_python(src))
    assert got == _by_id([meta, q])


def test_local_class_is_rejected_as_not_importable() -> None:
    class Local(EntityInstance):
        name: str

    with pytest.raises(ValueError, match="importable as a module attribute"):
        serialize.to_python([Local(id="local", name="Local")])


def test_from_python_returns_only_explicitly_emitted_instances() -> None:
    src = serialize.to_python([WorksFor(id="wf1", subject=alice, object_=acme)])
    src += "\nextra = Person(id='extra', name='Extra')\n"
    got = _by_id(serialize.from_python(src))
    assert set(got) == {"alice", "acme", "wf1"}
