"""Datalog engine tests (Python-native rules, no text grammar)."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

import datalog
import rules
from base import BaseStatement, Functional, Provenance, Transitive
from example import Believes, Employs, Knows, Person, WorksFor, acme, alice, bob
from rules import Rule, Var, lit, variable, variables

o, p = variables("o p")
x, y, z = variables("x y z")


def _wf() -> WorksFor:
    return WorksFor(id="wf1", subject=alice, object_=acme, truth_status="asserted_true")


class Ancestor(BaseStatement[Person, Person], Transitive):
    """Ancestor; transitive for these tests."""


class Manages(BaseStatement[Person, Person], Functional):
    """Functional (integrity constraint the engine can't compile)."""


def _chain(*ids: str) -> list[Ancestor]:
    people = {i: Person(id=i, name=i.upper()) for i in ids}
    return [
        Ancestor(
            id=f"{a}->{b}",
            subject=people[a],
            object_=people[b],
            truth_status="asserted_true",
        )
        for a, b in zip(ids, ids[1:])
    ]


# --- Variable helpers ------------------------------------------------------- #


def test_variable_returns_var() -> None:
    v = variable("x")
    assert isinstance(v, Var)
    assert v.name == "x"


def test_variable_and_variables_are_consistent() -> None:
    (vx,) = variables("x")
    assert variable("x") == vx


# --- Inverse ---------------------------------------------------------------- #


def test_hand_written_inverse_rule_derives_employs() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts([_wf()])
    eng.add_rule(Rule(lit(Employs, o, p), (lit(WorksFor, p, o),)))
    (emp,) = eng.infer()
    assert isinstance(emp, Employs)
    assert emp.subject is acme and emp.object_ is alice


def test_trait_compiled_inverse_matches_hand_written() -> None:
    trait_eng = datalog.Engine()
    assert 0 == trait_eng.add_facts([_wf()])
    trait_eng.add_traits(Employs)
    (from_trait,) = trait_eng.infer()

    rule_eng = datalog.Engine()
    assert 0 == rule_eng.add_facts([_wf()])
    rule_eng.add_rule(Rule(lit(Employs, o, p), (lit(WorksFor, p, o),)))
    (from_rule,) = rule_eng.infer()

    assert from_trait.id == from_rule.id
    assert (from_trait.subject.id, from_trait.object_.id) == (
        from_rule.subject.id,
        from_rule.object_.id,
    )


# --- Symmetric -------------------------------------------------------------- #


def test_symmetric_trait_derives_reverse() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts(
        [Knows(id="k1", subject=alice, object_=bob, truth_status="asserted_true")]
    )
    eng.add_traits(Knows)
    derived = eng.infer()
    assert any(s.subject is bob and s.object_ is alice for s in derived)


# --- Transitivity ----------------------------------------------------------- #


def test_transitivity_derives_closure() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts(_chain("a", "b", "c"))
    eng.add_traits(Ancestor)
    derived = {(s.subject.id, s.object_.id) for s in eng.infer()}
    assert ("a", "c") in derived


def test_transitivity_longer_chain_full_closure() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts(_chain("a", "b", "c", "d"))
    eng.add_traits(Ancestor)
    eng.infer()
    pairs = {(k.split("(")[1].split(",")[0], k.split(",")[1][:-1]) for k in eng._known}
    for expected in (("a", "c"), ("b", "d"), ("a", "d")):
        assert expected in pairs


# --- Fixed-point stability -------------------------------------------------- #


def test_fixpoint_stable_on_second_call() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts([_wf()])
    eng.add_rule(Rule(lit(Employs, o, p), (lit(WorksFor, p, o),)))
    eng.infer()
    assert eng.infer() == []


def test_infer_constructs_each_new_fact_once(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts(_chain("a", "b", "c", "d"))
    eng.add_traits(Ancestor)

    init_calls = 0
    original_init = cast(Any, Ancestor.__init__)

    def counting_init(self: Ancestor, *args: object, **kwargs: object) -> None:
        nonlocal init_calls
        init_calls += 1
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(Ancestor, "__init__", counting_init)

    derived = eng.infer()

    assert init_calls == len(derived)


# --- Derived-fact id and provenance ----------------------------------------- #


def test_derived_fact_has_content_addressed_id() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts([_wf()])
    eng.add_rule(Rule(lit(Employs, o, p), (lit(WorksFor, p, o),)))
    (emp,) = eng.infer()
    assert emp.id == "example.Employs(acme,alice)"


def test_derived_fact_grounded_with_rule_source() -> None:
    eng = datalog.Engine()
    assert 0 == eng.add_facts([_wf()])
    rule = Rule(lit(Employs, o, p), (lit(WorksFor, p, o),))
    eng.add_rule(rule)
    (emp,) = eng.infer()
    assert emp.provenance is not None
    (prov,) = emp.provenance
    assert prov.extraction_method == "inferred"
    assert prov.source == repr(rule)  # points back at the rule


# --- Only the asserted graph is reasoned over ------------------------------- #


def test_add_facts_ignores_non_asserted_true() -> None:
    disputed = WorksFor(id="wf2", subject=alice, object_=acme, truth_status="disputed")
    eng = datalog.Engine()
    eng.add_facts([disputed])
    eng.add_rule(Rule(lit(Employs, o, p), (lit(WorksFor, p, o),)))
    assert eng.infer() == []


# --- Type safety at derivation ---------------------------------------------- #


def test_domain_range_violation_raises_validation_error() -> None:
    # Derives WorksFor(acme, alice) — but WorksFor requires a Person subject.
    eng = datalog.Engine()
    assert 0 == eng.add_facts([_wf()])
    eng.add_rule(Rule(lit(WorksFor, o, p), (lit(WorksFor, p, o),)))
    with pytest.raises(ValidationError):
        eng.infer()


# --- Exception paths -------------------------------------------------------- #


def test_fixpoint_error_is_a_rule_error() -> None:
    assert issubclass(rules.FixpointError, rules.RuleError)


def test_fixpoint_error_raised_on_non_convergence() -> None:
    # a->b->c->d needs two rounds; cap at one.
    eng = datalog.Engine(max_iterations=1)
    assert 0 == eng.add_facts(_chain("a", "b", "c", "d"))
    eng.add_traits(Ancestor)
    with pytest.raises(rules.FixpointError):
        eng.infer()


def test_add_rule_raises_on_unsafe_rule() -> None:
    eng = datalog.Engine()
    with pytest.raises(rules.UnsafeRuleError):
        eng.add_rule(Rule(lit(Ancestor, x, z), (lit(Ancestor, x, y),)))  # ?z unbound


def test_add_rule_raises_on_higher_order_literal() -> None:
    inner = _wf()  # a statement used as a literal argument
    eng = datalog.Engine()
    with pytest.raises(rules.UnsupportedRuleError):
        eng.add_rule(Rule(lit(Believes, p, inner), (lit(WorksFor, p, o),)))


def test_add_facts_raises_on_higher_order_fact() -> None:
    outer = Believes(
        id="b1", subject=alice, object_=_wf(), truth_status="asserted_true"
    )
    eng = datalog.Engine()
    with pytest.raises(rules.UnsupportedRuleError):
        assert 0 == eng.add_facts([outer])


def test_add_facts_raises_on_higher_order_fact_even_if_not_asserted() -> None:
    outer = Believes(id="b1", subject=alice, object_=_wf(), truth_status="hypothetical")
    eng = datalog.Engine()
    with pytest.raises(rules.UnsupportedRuleError):
        assert 0 == eng.add_facts([outer])


def test_add_facts_is_atomic_on_invalid_batch() -> None:
    outer = Believes(
        id="b1", subject=alice, object_=_wf(), truth_status="asserted_true"
    )
    eng = datalog.Engine()
    with pytest.raises(rules.UnsupportedRuleError):
        assert 0 == eng.add_facts([_wf(), outer])
    assert eng._known == {}
    assert eng._facts_by_pred == {}
    assert eng._facts_by_pred_subj == {}
    assert eng._instance_index == {}


def test_add_facts_merges_corroborating_duplicate_fact() -> None:
    prov1 = Provenance(source="hr.csv", extraction_method="manual")
    prov2 = Provenance(source="wiki", extraction_method="model_extraction")
    wf1 = WorksFor(
        id="wf1",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov1,),
    )
    wf2 = WorksFor(
        id="wf2",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov2,),
    )
    eng = datalog.Engine()
    assert 0 == eng.add_facts([wf1, wf2])
    stored = eng._known["example.WorksFor(alice,acme)"]
    assert stored.id == "wf1"
    assert stored.provenance == (prov1, prov2)


def test_add_fact_after_infer_merges_provenance_with_inferred() -> None:
    eng = datalog.Engine()
    rule = Rule(lit(Employs, o, p), (lit(WorksFor, p, o),))
    assert 0 == eng.add_facts([_wf()])
    eng.add_rule(rule)
    eng.infer()
    asserted = Employs(
        id="manual-employs",
        subject=acme,
        object_=alice,
        truth_status="asserted_true",
        provenance=(Provenance(source="hr.csv", extraction_method="manual"),),
    )
    assert 0 == eng.add_facts([asserted])
    stored = eng._known["example.Employs(acme,alice)"]
    assert stored.id == "example.Employs(acme,alice)"
    assert stored.provenance == (
        Provenance(source=repr(rule), extraction_method="inferred"),
        Provenance(source="hr.csv", extraction_method="manual"),
    )


def test_add_facts_duplicate_lookup_does_not_depend_on_truthiness() -> None:
    class FalsyWorksFor(WorksFor):
        def __bool__(self) -> bool:
            return False

    prov1 = Provenance(source="hr.csv", extraction_method="manual")
    prov2 = Provenance(source="wiki", extraction_method="model_extraction")
    wf1 = FalsyWorksFor(
        id="wf1",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov1,),
    )
    wf2 = FalsyWorksFor(
        id="wf2",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov2,),
    )

    eng = datalog.Engine()
    assert 0 == eng.add_facts([wf1, wf2])

    stored = None
    for key in eng._known.keys():
        if key.endswith("FalsyWorksFor(alice,acme)"):
            stored = eng._known[key]
            break
    assert stored is not None
    assert stored.id == "wf1"
    assert stored.provenance == (prov1, prov2)


def test_add_traits_raises_on_uncompilable_trait() -> None:
    eng = datalog.Engine()
    with pytest.raises(rules.UnsupportedRuleError):
        eng.add_traits(Manages)  # Functional is not a derivation
