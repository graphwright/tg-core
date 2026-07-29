"""Demo loader for Sherlock JSONL data vendored in this repository.

The mystery demo (`solve_mystery`) runs a genuine Horn clause through the
datalog Engine's real API (`add_facts` -> `add_rule` -> `infer`). It reports the
candidate hiding places that *deduction alone* supports, and is explicit about
what deduction cannot do: it cannot, on the current dataset, single out one
place, because the graph contains no edge tying the reveal event to a location.
Ranking the candidates is exactly the job for the probabilistic layer.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path
from typing import cast

from datalog import Engine
from rules import Rule, lit, variables

from base import AnyStmt, BaseStatement, Instance
from graph import Graph
from serialize import to_python
from sherlock.importer import load_story_graph
from sherlock.problog_adapter import (
    ProbLogUnavailableError,
    build_candidate_place_program,
    evaluate_program,
    evaluate_candidate_place_marginals,
)
from sherlock.problog_scenario import (
    scandal_evidence_lines,
    scandal_explanatory_rules,
    scandal_primitive_lines,
    scandal_ranking_rules,
)
from sherlock.schema import (
    AssociatedWith,
    HappenedIn,
    Involves,
    OccurredAt,
    PhysicallyIn,
    Possesses,
)


def _count_entity_types(graph: Graph) -> Counter[str]:
    counts: Counter[str] = Counter()
    for inst in graph.by_id.values():
        if hasattr(inst, "subject") and hasattr(inst, "object_"):
            continue
        counts[type(inst).__name__] += 1
    return counts


def _count_predicates(graph: Graph) -> Counter[str]:
    counts: Counter[str] = Counter()
    seen_statement_ids: set[str] = set()
    for edges in graph.out_edges.values():
        for edge in edges:
            if edge.id in seen_statement_ids:
                continue
            seen_statement_ids.add(edge.id)
            counts[type(edge).__name__] += 1
    return counts


def serialize_entire_sherlock_graph() -> None:
    dataset_dir = os.environ.get(
        "SHERLOCK_DATASET_DIR", str(Path(__file__).resolve().parent / "data")
    )
    story_prefix = os.environ.get("SHERLOCK_STORY_PREFIX", "bohemia")
    min_conf_raw = os.environ.get("SHERLOCK_MIN_CONFIDENCE")
    min_conf = float(min_conf_raw) if min_conf_raw is not None else None

    graph, _report = load_story_graph(
        dataset_dir=dataset_dir,
        story_prefix=story_prefix,
        confidence_threshold=min_conf,
    )

    # Stable order makes serialization output deterministic across runs.
    instances: list[Instance] = sorted(graph.by_id.values(), key=lambda inst: inst.id)
    source = to_python(instances)
    print(source)


def _resolve_id_by_text(
    graph: Graph, preferred_id: str, required_tokens: tuple[str, ...]
) -> str | None:
    """Resolve an id by exact match, then by canonical/aliases token search."""
    if preferred_id in graph.by_id:
        return preferred_id

    token_set = tuple(t.lower() for t in required_tokens)
    matches: list[str] = []
    for inst in graph.by_id.values():
        canonical = getattr(inst, "canonical", "")
        aliases = getattr(inst, "aliases", ())
        haystack = " ".join(
            [inst.id, str(canonical), *(str(a) for a in aliases)]
        ).lower()
        if all(tok in haystack for tok in token_set):
            matches.append(inst.id)

    if not matches:
        return None
    return sorted(matches)[0]


def _asserted_facts(graph: Graph) -> list[AnyStmt]:
    """Every statement in the graph, in stable id order.

    The engine's ``add_facts`` reasons only over ``asserted_true`` statements
    (it skips ``hypothetical`` and ``disputed`` ones and returns the skip
    count), so passing the whole set is safe -- sorting keeps derivation order
    deterministic across runs.
    """
    facts: list[AnyStmt] = []
    for inst in graph.by_id.values():
        if isinstance(inst, BaseStatement):
            facts.append(cast(AnyStmt, inst))
    return sorted(facts, key=lambda stmt: stmt.id)


def _name(graph: Graph, entity_id: str) -> str:
    inst = graph.by_id.get(entity_id)
    return str(getattr(inst, "canonical", entity_id)) if inst is not None else entity_id


def _photo_candidate_places_via_rule(
    graph: Graph, photo_id: str, *, require_happened_in: bool
) -> tuple[int, list[str]]:
    """Run the mystery Horn clause and return (skipped_facts, candidate places)."""
    p, o, e, m, room = variables("p o e m room")
    body = [
        lit(Possesses, p, o),
        lit(Involves, e, p),
        lit(OccurredAt, e, m),
        lit(AssociatedWith, p, room),
    ]
    if require_happened_in:
        body.append(lit(HappenedIn, e, room))
    rule = Rule(lit(PhysicallyIn, o, room), tuple(body))

    engine = Engine(max_iterations=64)
    skipped = engine.add_facts(_asserted_facts(graph))
    engine.add_rule(rule)
    derived = engine.infer()

    photo_places = sorted(
        fact.object_.id
        for fact in derived
        if isinstance(fact, PhysicallyIn) and fact.subject.id == photo_id
    )
    return skipped, photo_places


def solve_mystery(graph: Graph) -> None:
    """Deduce where the photograph could be, honestly.

    The Horn clause below says: an object is physically in a place if its
    possessor is involved in some event that occurred at some moment, and that
    possessor is associated with the place. This runs through the *real* Engine
    API -- no adapters, no fallbacks. If the rule cannot fire, the demo says so
    and stops; it never substitutes a hard-coded answer.

    Deduction yields the *set* of places the possessor is associated with. It
    cannot, on this dataset, narrow to one: the graph has no edge linking the
    reveal event to a location (the source triplets contain no event->location
    predicate at all), so the discriminating signal Doyle's readers use -- the
    sitting room is where Holmes is carried at the very moment Irene bolts to
    the photograph -- is not present as a fact. Picking the sitting room out of
    the candidate set is a ranking problem, which is where probabilistic
    inference (evidence conditioning on the shared reveal-moment) comes in.
    """
    photo_id = _resolve_id_by_text(graph, "obj:irene_adlers_photograph", ("photo",))
    if photo_id is None:
        print("Could not solve mystery: could not resolve the photograph id.")
        return

    print("Mystery demo (Horn clause, real datalog engine)")
    print(
        "  Rule: PhysicallyIn(o, room) :- "
        "Possesses(p, o), Involves(e, p), OccurredAt(e, m), "
        "AssociatedWith(p, room), HappenedIn(e, room)"
    )

    skipped, photo_places = _photo_candidate_places_via_rule(
        graph, photo_id, require_happened_in=True
    )

    print(
        f"  loaded facts (skipped {skipped} non-asserted), "
        f"candidate places from rule: {len(photo_places)}"
    )

    if not photo_places:
        print("Deduction derived no hiding place for the photograph.")
        return

    if len(photo_places) == 1:
        place_id = photo_places[0]
        print(
            f"Deduced uniquely: {_name(graph, photo_id)} is in {_name(graph, place_id)}"
        )
        return

    print(
        f"Deduction narrows {_name(graph, photo_id)} to "
        f"{len(photo_places)} candidate places (it cannot rank them):"
    )
    for place_id in photo_places:
        print(f"  - {_name(graph, place_id)}  ({place_id})")
    print(
        "\nSingling out the sitting room needs information the graph does not "
        "hold as a fact: the reveal event carries its location only in its "
        "name, never as an edge. That is a ranking problem for the "
        "probabilistic layer, not a gap deduction can close."
    )


def solve_mystery_problog(graph: Graph) -> None:
    """Optional ProbLog-backed evaluator over the same graph and rule structure."""
    photo_id = _resolve_id_by_text(graph, "obj:irene_adlers_photograph", ("photo",))
    if photo_id is None:
        print("Could not run probabilistic mystery demo: photograph id not found.")
        return

    skipped, photo_places = _photo_candidate_places_via_rule(
        graph, photo_id, require_happened_in=False
    )
    if not photo_places:
        print("Probabilistic demo: deduction produced no candidate places to rank.")
        return

    print("Mystery demo (ProbLog adapter, optional evaluator)")
    print(f"  candidates from deduction: {len(photo_places)} (skipped {skipped} facts)")

    primitive_lines = [
        *scandal_primitive_lines(),
        *scandal_explanatory_rules(),
        *scandal_ranking_rules(),
    ]
    evidence_lines = scandal_evidence_lines(graph)
    print(f"  conditioning evidence lines: {len(evidence_lines)}")

    program = build_candidate_place_program(
        graph,
        object_id=photo_id,
        candidate_place_ids=photo_places,
        query_predicate="photo_in_place",
        query_arity=1,
        primitive_lines=primitive_lines,
        evidence_lines=evidence_lines,
    )

    try:
        query_result = evaluate_program(program.source)
    except ProbLogUnavailableError as exc:
        print(f"  ProbLog unavailable: {exc}")
        print("  Emitted ProbLog program follows for inspection:")
        print(program.source)
        return

    _, marginals = evaluate_candidate_place_marginals(
        graph,
        object_id=photo_id,
        candidate_place_ids=photo_places,
        query_predicate="photo_in_place",
        query_arity=1,
        primitive_lines=primitive_lines,
        evidence_lines=evidence_lines,
        evaluator=lambda source: query_result,
    )

    ranked = sorted(marginals.items(), key=lambda item: item[1], reverse=True)
    print("  ranked candidates:")
    for place_id, prob in ranked:
        print(f"    {_name(graph, place_id)} ({place_id}): {prob:.6f}")


def _load_graph_from_env() -> Graph:
    """Load graph using the same environment knobs as other demo paths."""
    dataset_dir = os.environ.get(
        "SHERLOCK_DATASET_DIR", str(Path(__file__).resolve().parent / "data")
    )
    story_prefix = os.environ.get("SHERLOCK_STORY_PREFIX", "bohemia")
    min_conf_raw = os.environ.get("SHERLOCK_MIN_CONFIDENCE")
    min_conf = float(min_conf_raw) if min_conf_raw is not None else None

    graph, _report = load_story_graph(
        dataset_dir=dataset_dir,
        story_prefix=story_prefix,
        confidence_threshold=min_conf,
    )
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load and summarize Sherlock JSONL data"
    )
    parser.add_argument(
        "--dataset-dir",
        default=str(Path(__file__).resolve().parent / "data"),
        help="Directory containing bohemia_*.jsonl files (default: sherlock/data)",
    )
    parser.add_argument(
        "--story-prefix",
        default="bohemia",
        help="Prefix for dataset files like <prefix>_triplets.jsonl",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Optional extraction confidence threshold",
    )
    args = parser.parse_args()

    graph, report = load_story_graph(
        dataset_dir=args.dataset_dir,
        story_prefix=args.story_prefix,
        confidence_threshold=args.min_confidence,
    )

    print("Sherlock import summary")
    print(f"dataset_dir: {args.dataset_dir}")
    print(f"story_prefix: {args.story_prefix}")
    print(f"entities_loaded: {report.entities_loaded}")
    print(f"events_loaded: {report.events_loaded}")
    print(f"moments_loaded: {report.moments_loaded}")
    print(f"statements_loaded: {report.statements_loaded}")
    print(f"placeholders_created: {report.placeholders_created}")
    print(f"skipped_low_confidence: {report.skipped_low_confidence}")
    print(f"unknown_predicates: {list(report.unknown_predicates)}")

    entity_counts = _count_entity_types(graph)
    predicate_counts = _count_predicates(graph)

    print("entity_types:")
    for name in sorted(entity_counts):
        print(f"  {name}: {entity_counts[name]}")

    print("predicates:")
    for name in sorted(predicate_counts):
        print(f"  {name}: {predicate_counts[name]}")


if __name__ == "__main__":
    if os.environ.get("ENTIRE_GRAPH"):
        serialize_entire_sherlock_graph()
    elif os.environ.get("SOLVE_MYSTERY_PROBLOG"):
        solve_mystery_problog(_load_graph_from_env())
    elif os.environ.get("SOLVE_MYSTERY"):
        solve_mystery(_load_graph_from_env())
    else:
        main()
