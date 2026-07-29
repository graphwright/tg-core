from __future__ import annotations

from sherlock.problog_scenario import (
    SCANDAL_EVIDENCE,
    PrimitiveRandomVariable,
    SCANDAL_PRIMITIVES,
    scandal_evidence_lines,
    scandal_explanatory_rules,
    scandal_primitive_lines,
    scandal_ranking_rules,
)
from tests.test_sherlock_problog_adapter import _sample_graph


def test_scandal_primitives_render_as_annotated_facts() -> None:
    lines = scandal_primitive_lines()

    assert len(lines) == len(SCANDAL_PRIMITIVES)
    assert all("::" in line for line in lines)
    assert all(line.endswith(".") for line in lines)


def test_scandal_primitive_symbols_are_unique() -> None:
    symbols = [primitive.symbol for primitive in SCANDAL_PRIMITIVES]

    assert len(symbols) == len(set(symbols))


def test_scandal_explanatory_rules_are_deterministic_clauses() -> None:
    rules = scandal_explanatory_rules()

    assert rules
    assert all(":-" in rule for rule in rules)
    assert all(rule.endswith(".") for rule in rules)


def test_primitive_to_problog_precision_is_stable() -> None:
    rv = PrimitiveRandomVariable(
        symbol="example_coin",
        probability=0.5,
        rationale="Example rationale",
    )

    assert rv.to_problog() == "0.500000::example_coin."


def test_scandal_evidence_lines_render_true_evidence() -> None:
    lines = scandal_evidence_lines()

    assert len(lines) == len(SCANDAL_EVIDENCE)
    assert all(line.startswith("evidence(") for line in lines)
    assert all(line.endswith("true).") for line in lines)


def test_scandal_evidence_lines_filter_to_supported_graph_observations() -> None:
    graph, _photo_id, _room_id = _sample_graph()

    lines = scandal_evidence_lines(graph)

    assert lines
    assert len(lines) < len(SCANDAL_EVIDENCE)
    assert any("holmes_carried_into_sitting_room" in line for line in lines)


def test_scandal_ranking_rules_define_photo_hypothesis() -> None:
    rules = scandal_ranking_rules()

    assert any(rule.startswith("candidate_place(Place) :-") for rule in rules)
    assert any("reveal_coincidence_place(Place)" in rule for rule in rules)
    assert any("photo_in_place(Place)" in rule for rule in rules)
