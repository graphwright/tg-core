"""Tests for Sherlock dataset schema/import in the sherlock subdirectory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from base import Symmetric, Trait, get_inverse
from sherlock.importer import load_story_graph
from sherlock.schema import (
    AssociatedWith,
    Contradicts,
    Event,
    HappenedIn,
    Involves,
    KnewAt,
    Knows,
    Location,
    Moment,
    Person,
)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def test_load_story_graph_builds_entities_and_statements(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "bohemia_entities.jsonl",
        [
            {
                "canonical": "Sherlock Holmes",
                "aliases": ["Holmes"],
                "type": "person",
                "wiki_url": "https://bakerstreet.fandom.com/wiki/Sherlock_Holmes",
                "entity_id": "wiki:Sherlock_Holmes",
            },
            {
                "canonical": "Dr. Watson",
                "aliases": ["Watson"],
                "type": "person",
                "wiki_url": "https://bakerstreet.fandom.com/wiki/John_Watson",
                "entity_id": "wiki:John_Watson",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "bohemia_events.jsonl",
        [
            {
                "id": "sib:event:watson_visits_holmes",
                "description": "Watson visits Holmes.",
                "sentence_ids": [1],
                "para": 1,
                "participants": ["https://bakerstreet.fandom.com/wiki/John_Watson"],
                "extraction_confidence": 0.95,
            }
        ],
    )
    _write_jsonl(
        tmp_path / "bohemia_moments.jsonl",
        [
            {
                "id": "sib:moment:night_of_20_march_1888",
                "label": "Night of 20 March 1888",
                "event_id": "sib:event:watson_visits_holmes",
                "narrator_id": None,
                "sentence_ids": [1],
                "extraction_confidence": 0.99,
            }
        ],
    )
    _write_jsonl(
        tmp_path / "bohemia_triplets.jsonl",
        [
            {
                "id": "stmt:sib:event:watson_visits_holmes:Involves:wiki:John_Watson",
                "predicate": "Involves",
                "subject_id": "sib:event:watson_visits_holmes",
                "subject_type": "Event",
                "object_id": "wiki:John_Watson",
                "object_type": "Person",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 1,
                "sentence_ids": [1],
                "asserting_narrator_id": "wiki:John_Watson",
                "extraction_method": "llm-triplet-extraction",
                "extraction_confidence": 0.99,
                "narrator_confidence": None,
            },
            {
                "id": "stmt:sib:event:watson_visits_holmes:OccurredAt:sib:moment:night_of_20_march_1888",
                "predicate": "OccurredAt",
                "subject_id": "sib:event:watson_visits_holmes",
                "subject_type": "Event",
                "object_id": "sib:moment:night_of_20_march_1888",
                "object_type": "Moment",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 1,
                "sentence_ids": [1],
                "asserting_narrator_id": "wiki:John_Watson",
                "extraction_method": "llm-triplet-extraction",
                "extraction_confidence": 0.99,
                "narrator_confidence": None,
            },
        ],
    )

    graph, report = load_story_graph(tmp_path)

    watson = graph.get("wiki:John_Watson")
    event = graph.get("sib:event:watson_visits_holmes")
    moment = graph.get("sib:moment:night_of_20_march_1888")

    assert isinstance(watson, Person)
    assert isinstance(event, Event)
    assert isinstance(moment, Moment)

    involves_edges = graph.edges_from(
        "sib:event:watson_visits_holmes", pred_type=Involves
    )
    assert len(involves_edges) == 1
    prov = involves_edges[0].provenance
    assert prov is not None
    assert prov[0].extraction_method == "model_extraction"
    assert report.statements_loaded == 2
    assert report.placeholders_created == 0


def test_load_story_graph_creates_placeholders_for_missing_ids(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "bohemia_entities.jsonl", [])
    _write_jsonl(tmp_path / "bohemia_events.jsonl", [])
    _write_jsonl(tmp_path / "bohemia_moments.jsonl", [])
    _write_jsonl(
        tmp_path / "bohemia_triplets.jsonl",
        [
            {
                "id": "stmt:sib:event:missing:Involves:wiki:Missing",
                "predicate": "Involves",
                "subject_id": "sib:event:missing",
                "subject_type": "Event",
                "object_id": "wiki:Missing",
                "object_type": "Person",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 1,
                "sentence_ids": [1],
                "asserting_narrator_id": None,
                "extraction_method": "llm-triplet-extraction",
                "extraction_confidence": 0.9,
                "narrator_confidence": None,
            }
        ],
    )

    graph, report = load_story_graph(tmp_path)

    assert isinstance(graph.get("sib:event:missing"), Event)
    assert isinstance(graph.get("wiki:Missing"), Person)
    assert report.placeholders_created == 2


def test_load_story_graph_real_dataset_if_available() -> None:
    dataset_dir = Path(__file__).resolve().parents[1] / "sherlock" / "data"
    if not dataset_dir.exists():
        pytest.skip("Vendored dataset sherlock/data not available in this environment")

    graph, report = load_story_graph(dataset_dir)

    assert report.statements_loaded > 0
    holmes = graph.get("wiki:Sherlock_Holmes")
    assert isinstance(holmes, Person)


def test_load_story_graph_adds_carry_event_location_hint_if_available() -> None:
    dataset_dir = Path(__file__).resolve().parents[1] / "sherlock" / "data"
    if not dataset_dir.exists():
        pytest.skip("Vendored dataset sherlock/data not available in this environment")

    graph, _report = load_story_graph(dataset_dir)
    hinted_edges = graph.edges_from(
        "sib:event:holmes_carried_into_sitting_room", pred_type=HappenedIn
    )
    assert any(
        edge.object_.id == "place:irene_adlers_sitting-room" for edge in hinted_edges
    )


def test_load_story_graph_hydrates_higher_order_predicates_in_order(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "bohemia_entities.jsonl",
        [
            {
                "canonical": "Sherlock Holmes",
                "aliases": ["Holmes"],
                "type": "person",
                "entity_id": "wiki:Sherlock_Holmes",
            },
            {
                "canonical": "Dr. Watson",
                "aliases": ["Watson"],
                "type": "person",
                "entity_id": "wiki:John_Watson",
            },
        ],
    )
    _write_jsonl(tmp_path / "bohemia_events.jsonl", [])
    _write_jsonl(tmp_path / "bohemia_moments.jsonl", [])
    knows_id = "stmt:knows:holmes:watson"
    knew_at_id = "stmt:knew_at:holmes:knows"
    _write_jsonl(
        tmp_path / "bohemia_triplets.jsonl",
        [
            {
                "id": knows_id,
                "predicate": "Knows",
                "subject_id": "wiki:Sherlock_Holmes",
                "subject_type": "Person",
                "object_id": "wiki:John_Watson",
                "object_type": "Person",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 1,
                "sentence_ids": [1],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.99,
                "narrator_confidence": None,
            },
            {
                "id": knew_at_id,
                "predicate": "KnewAt",
                "subject_id": "wiki:Sherlock_Holmes",
                "subject_type": "Person",
                "object_id": knows_id,
                "object_type": "Knows",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 2,
                "sentence_ids": [2],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.95,
                "narrator_confidence": None,
            },
        ],
    )

    graph, report = load_story_graph(tmp_path)

    knew_edges = graph.edges_from("wiki:Sherlock_Holmes", pred_type=KnewAt)
    assert len(knew_edges) == 1
    assert isinstance(knew_edges[0].object_, Knows)
    assert knew_edges[0].object_.id == knows_id
    assert report.unresolved_higher_order == ()


def test_load_story_graph_defers_higher_order_rows_until_referenced_statement_exists(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "bohemia_entities.jsonl",
        [
            {
                "canonical": "Sherlock Holmes",
                "type": "person",
                "entity_id": "wiki:Sherlock_Holmes",
            },
            {
                "canonical": "Dr. Watson",
                "type": "person",
                "entity_id": "wiki:John_Watson",
            },
        ],
    )
    _write_jsonl(tmp_path / "bohemia_events.jsonl", [])
    _write_jsonl(tmp_path / "bohemia_moments.jsonl", [])
    knows_id = "stmt:knows:holmes:watson"
    knew_at_id = "stmt:knew_at:holmes:knows"
    _write_jsonl(
        tmp_path / "bohemia_triplets.jsonl",
        [
            {
                "id": knew_at_id,
                "predicate": "KnewAt",
                "subject_id": "wiki:Sherlock_Holmes",
                "subject_type": "Person",
                "object_id": knows_id,
                "object_type": "Knows",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 2,
                "sentence_ids": [2],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.95,
                "narrator_confidence": None,
            },
            {
                "id": knows_id,
                "predicate": "Knows",
                "subject_id": "wiki:Sherlock_Holmes",
                "subject_type": "Person",
                "object_id": "wiki:John_Watson",
                "object_type": "Person",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 1,
                "sentence_ids": [1],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.99,
                "narrator_confidence": None,
            },
        ],
    )

    graph, report = load_story_graph(tmp_path)

    knew_edges = graph.edges_from("wiki:Sherlock_Holmes", pred_type=KnewAt)
    assert len(knew_edges) == 1
    assert isinstance(knew_edges[0].object_, Knows)
    assert knew_edges[0].object_.id == knows_id
    assert report.unresolved_higher_order == ()


def test_load_story_graph_hydrates_contradicts_between_statements(
    tmp_path: Path,
) -> None:
    _write_jsonl(
        tmp_path / "bohemia_entities.jsonl",
        [
            {
                "canonical": "Sherlock Holmes",
                "type": "person",
                "entity_id": "wiki:Sherlock_Holmes",
            },
            {
                "canonical": "Dr. Watson",
                "type": "person",
                "entity_id": "wiki:John_Watson",
            },
        ],
    )
    _write_jsonl(tmp_path / "bohemia_events.jsonl", [])
    _write_jsonl(tmp_path / "bohemia_moments.jsonl", [])
    knows_id = "stmt:knows:holmes:watson"
    inverse_knows_id = "stmt:knows:watson:holmes"
    contradicts_id = "stmt:contradicts:knows"
    _write_jsonl(
        tmp_path / "bohemia_triplets.jsonl",
        [
            {
                "id": knows_id,
                "predicate": "Knows",
                "subject_id": "wiki:Sherlock_Holmes",
                "subject_type": "Person",
                "object_id": "wiki:John_Watson",
                "object_type": "Person",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 1,
                "sentence_ids": [1],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.99,
                "narrator_confidence": None,
            },
            {
                "id": inverse_knows_id,
                "predicate": "Knows",
                "subject_id": "wiki:John_Watson",
                "subject_type": "Person",
                "object_id": "wiki:Sherlock_Holmes",
                "object_type": "Person",
                "truth_status": "asserted_false",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 2,
                "sentence_ids": [2],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.8,
                "narrator_confidence": None,
            },
            {
                "id": contradicts_id,
                "predicate": "Contradicts",
                "subject_id": knows_id,
                "subject_type": "Knows",
                "object_id": inverse_knows_id,
                "object_type": "Knows",
                "truth_status": "asserted_true",
                "story_id": "scandal_in_bohemia",
                "paragraph_index": 3,
                "sentence_ids": [3],
                "asserting_narrator_id": None,
                "extraction_method": "model_extraction",
                "extraction_confidence": 0.9,
                "narrator_confidence": None,
            },
        ],
    )

    graph, report = load_story_graph(tmp_path)

    contradicts = graph.get(contradicts_id)
    assert isinstance(contradicts, Contradicts)
    assert contradicts.subject.id == knows_id
    assert contradicts.object_.id == inverse_knows_id
    assert report.unresolved_higher_order == ()
def test_sherlock_entity_str_returns_canonical() -> None:
    holmes = Person(id="wiki:Sherlock_Holmes", canonical="Sherlock Holmes")

    assert str(holmes) == holmes.canonical


def test_story_statement_field_set_is_stable() -> None:
    expected = {
        "id",
        "subject",
        "object_",
        "truth_status",
        "provenance",
        "story_id",
        "paragraph_index",
        "sentence_ids",
        "asserting_narrator_id",
        "extraction_confidence",
        "narrator_confidence",
        "raw_extraction_method",
    }

    assert set(Involves.model_fields) == expected


def test_contradicts_preserves_concrete_statement_types() -> None:
    holmes = Person(id="wiki:Sherlock_Holmes", canonical="Sherlock Holmes")
    watson = Person(id="wiki:John_Watson", canonical="Dr. Watson")
    baker_street = Location(
        id="place:221b_baker_street", canonical="221B Baker Street"
    )
    knows = Knows(
        id="stmt:knows",
        subject=holmes,
        object_=watson,
        truth_status="asserted_true",
        story_id="story",
    )
    associated = AssociatedWith(
        id="stmt:associated",
        subject=holmes,
        object_=baker_street,
        truth_status="asserted_true",
        story_id="story",
    )
    contradicts = Contradicts(
        id="stmt:contradicts",
        subject=knows,
        object_=associated,
        truth_status="asserted_true",
        story_id="story",
    )

    assert contradicts.subject is knows
    assert contradicts.object_ is associated
    assert isinstance(contradicts.subject, Knows)
    assert isinstance(contradicts.object_, AssociatedWith)
    assert issubclass(Contradicts, Symmetric)
    assert issubclass(Contradicts, Trait)


def test_knew_at_has_no_inverse() -> None:
    holmes = Person(id="wiki:Sherlock_Holmes", canonical="Sherlock Holmes")
    watson = Person(id="wiki:John_Watson", canonical="Dr. Watson")
    moment = Moment(id="sib:moment:1", canonical="A moment")
    knows = Knows(
        id="stmt:knows",
        subject=holmes,
        object_=watson,
        truth_status="asserted_true",
        story_id="story",
    )
    knew_at = KnewAt(
        id="stmt:knew-at",
        subject=holmes,
        object_=knows,
        moment=moment,
        truth_status="asserted_true",
        story_id="story",
    )

    assert knew_at.object_ is knows
    assert get_inverse(KnewAt) is None
