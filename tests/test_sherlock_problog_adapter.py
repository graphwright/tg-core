from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

import pytest

from graph import Graph
from sherlock.problog_adapter import (
    ProbLogUnavailableError,
    build_candidate_place_program,
    emit_asserted_facts,
    evaluate_candidate_place_marginals,
    evaluate_program,
)
from sherlock.schema import (
    AssociatedWith,
    Event,
    HappenedIn,
    Involves,
    Location,
    Moment,
    Object,
    OccurredAt,
    Person,
    Possesses,
)


def _sample_graph() -> tuple[Graph, str, str]:
    irene = Person(id="wiki:Irene_Adler", canonical="Irene Adler")
    photo = Object(id="obj:irene_adlers_photograph", canonical="Photograph")
    event = Event(
        id="sib:event:holmes_carried_into_sitting_room",
        canonical="Holmes carried into sitting room",
    )
    moment = Moment(
        id="sib:moment:holmes_learns_photograph_location",
        canonical="Reveal moment",
    )
    room = Location(
        id="place:irene_adlers_sitting-room", canonical="Irene Adler's sitting room"
    )

    facts: list[object] = [
        Possesses(
            id="s1",
            subject=irene,
            object_=photo,
            truth_status="asserted_true",
            story_id="scandal",
        ),
        Involves(
            id="s2",
            subject=event,
            object_=irene,
            truth_status="asserted_true",
            story_id="scandal",
        ),
        OccurredAt(
            id="s3",
            subject=event,
            object_=moment,
            truth_status="asserted_true",
            story_id="scandal",
        ),
        AssociatedWith(
            id="s4",
            subject=irene,
            object_=room,
            truth_status="asserted_true",
            story_id="scandal",
        ),
        HappenedIn(
            id="s5",
            subject=event,
            object_=room,
            truth_status="asserted_true",
            story_id="scandal",
        ),
    ]

    instances: list[object] = [irene, photo, event, moment, room, *facts]
    return Graph(instances), photo.id, room.id


def test_emit_asserted_facts_uses_statement_types() -> None:
    graph, _photo_id, room_id = _sample_graph()

    lines = emit_asserted_facts(graph)

    assert 'possesses("wiki:Irene_Adler", "obj:irene_adlers_photograph").' in lines
    assert (
        'happened_in("sib:event:holmes_carried_into_sitting_room", '
        f'"{room_id}").' in lines
    )


def test_build_candidate_place_program_emits_rule_and_query() -> None:
    graph, photo_id, room_id = _sample_graph()

    program = build_candidate_place_program(
        graph,
        object_id=photo_id,
        candidate_place_ids=[room_id],
        query_predicate="photo_in_place",
        primitive_lines=["0.900000::photo_is_real."],
        evidence_lines=[
            'evidence(happened_in("sib:event:holmes_carried_into_sitting_room", "place:irene_adlers_sitting-room"), true)'
        ],
    )

    assert "0.900000::photo_is_real." in program.source
    assert "physically_in(Object, Place)" in program.source
    assert (
        'candidate_place_1 :- photo_in_place("obj:irene_adlers_photograph", "place:irene_adlers_sitting-room").'
        in program.source
    )
    assert "query(candidate_place_1)." in program.source
    assert "evidence(happened_in" in program.source
    assert program.query_symbols == {"candidate_place_1": room_id}


def test_build_candidate_place_program_supports_unary_query_predicate() -> None:
    graph, photo_id, room_id = _sample_graph()

    program = build_candidate_place_program(
        graph,
        object_id=photo_id,
        candidate_place_ids=[room_id],
        query_predicate="photo_in_place",
        query_arity=1,
    )

    assert (
        'candidate_place_1 :- photo_in_place("place:irene_adlers_sitting-room").'
        in program.source
    )
    assert "query(candidate_place_1)." in program.source


def test_evaluate_candidate_place_marginals_uses_query_mapping() -> None:
    graph, photo_id, room_id = _sample_graph()

    def fake_evaluator(source: str) -> Mapping[str, float]:
        _ = source
        return {"candidate_place_1": 0.73}

    _program, marginals = evaluate_candidate_place_marginals(
        graph,
        object_id=photo_id,
        candidate_place_ids=[room_id],
        evaluator=fake_evaluator,
    )

    assert marginals[room_id] == pytest.approx(0.73)


def test_evaluate_program_raises_when_problog_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import_module = importlib.import_module

    def fake_import_module(name: str) -> Any:
        if name.startswith("problog"):
            raise ImportError("missing")
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(ProbLogUnavailableError):
        evaluate_program("query(dummy).")
