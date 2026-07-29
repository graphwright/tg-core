"""Import Sherlock JSONL datasets into typed graph instances."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

from base import ExtractionMethod, Provenance, TruthStatus
from graph import Graph
from sherlock.schema import (
    AssociatedWith,
    Event,
    HappenedIn,
    Involves,
    Knows,
    LocatedIn,
    Location,
    Moment,
    Object,
    OccurredAt,
    Organization,
    OtherEntity,
    Person,
    Possesses,
    SherlockEntity,
    StoryStatement,
)

EntityType = type[SherlockEntity]
PredicateType = type[StoryStatement[Any, Any]]


@dataclass(frozen=True)
class ImportReport:
    """Summary of what the Sherlock importer loaded and synthesized."""

    entities_loaded: int
    events_loaded: int
    moments_loaded: int
    statements_loaded: int
    placeholders_created: int
    skipped_low_confidence: int
    unknown_predicates: tuple[str, ...]


_ENTITY_TYPE_MAP: dict[str, EntityType] = {
    "person": Person,
    "organization": Organization,
    "place": Location,
    "location": Location,
    "object": Object,
    "event": Event,
    "moment": Moment,
    "other": OtherEntity,
}

_PREFIX_TYPE_MAP: dict[str, EntityType] = {
    "wiki": Person,
    "person": Person,
    "place": Location,
    "obj": Object,
    "sib": OtherEntity,
}

_PREDICATE_MAP: dict[str, PredicateType] = {
    "Involves": Involves,
    "OccurredAt": OccurredAt,
    "Possesses": Possesses,
    "AssociatedWith": AssociatedWith,
    "Knows": Knows,
    "LocatedIn": LocatedIn,
    "HappenedIn": HappenedIn,
}

# Curated event->location hints for places that appear in event ids/descriptions
# but are not emitted as explicit triplets in the source dataset.
_EVENT_LOCATION_HINTS: dict[str, str] = {
    "sib:event:holmes_carried_into_sitting_room": "place:irene_adlers_sitting-room",
    "sib:event:irene_grants_permission_sitting_room": "place:irene_adlers_sitting-room",
    "sib:event:norton_paces_sitting_room": "place:irene_adlers_sitting-room",
}


def _coerce_extraction_method(raw_method: str | None) -> ExtractionMethod:
    if raw_method == "manual":
        return "manual"
    if raw_method == "inferred":
        return "inferred"
    if raw_method == "quotation":
        return "quotation"
    if raw_method == "model_extraction":
        return "model_extraction"
    return "model_extraction"


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object in {path}, got {type(row)!r}")
            yield cast(dict[str, Any], row)


def _entity_type_for(raw_type: str | None, fallback_id: str) -> EntityType:
    if raw_type is not None:
        mapped = _ENTITY_TYPE_MAP.get(raw_type.lower())
        if mapped is not None:
            return mapped

    prefix = fallback_id.split(":", 1)[0]
    mapped = _PREFIX_TYPE_MAP.get(prefix)
    if mapped is not None:
        return mapped
    return OtherEntity


def _ensure_entity(
    registry: dict[str, SherlockEntity],
    entity_id: str,
    raw_type: str | None = None,
    canonical: str | None = None,
) -> tuple[SherlockEntity, bool]:
    existing = registry.get(entity_id)
    if existing is not None:
        return existing, False

    entity_cls = _entity_type_for(raw_type, entity_id)
    label = canonical if canonical is not None else entity_id
    created = entity_cls(
        id=entity_id,
        canonical=label,
        raw_type=raw_type,
    )
    registry[entity_id] = created
    return created, True


def load_story_graph(
    dataset_dir: str | Path,
    story_prefix: str = "bohemia",
    *,
    confidence_threshold: float | None = None,
) -> tuple[Graph, ImportReport]:
    """Load Sherlock JSONL files from `dataset_dir` into a typed Graph.

    Required files: `<story_prefix>_entities.jsonl` and
    `<story_prefix>_triplets.jsonl`.

    Optional enrichment files: `<story_prefix>_events.jsonl` and
    `<story_prefix>_moments.jsonl`.

    Missing ids referenced by triplets are synthesized as placeholder entities.
    """

    base_dir = Path(dataset_dir)
    entities_path = base_dir / f"{story_prefix}_entities.jsonl"
    events_path = base_dir / f"{story_prefix}_events.jsonl"
    moments_path = base_dir / f"{story_prefix}_moments.jsonl"
    triplets_path = base_dir / f"{story_prefix}_triplets.jsonl"

    registry: dict[str, SherlockEntity] = {}

    entities_loaded = 0
    events_loaded = 0
    moments_loaded = 0
    statements_loaded = 0
    placeholders_created = 0
    skipped_low_confidence = 0
    unknown_predicates: set[str] = set()

    for row in _iter_jsonl(entities_path):
        entity_id = cast(str, row["entity_id"])
        entity_cls = _entity_type_for(cast(str | None, row.get("type")), entity_id)
        aliases = tuple(cast(list[str], row.get("aliases", [])))
        canonical = cast(str, row.get("canonical", entity_id))
        entity = entity_cls(
            id=entity_id,
            canonical=canonical,
            aliases=aliases,
            wiki_url=cast(str | None, row.get("wiki_url")),
            raw_type=cast(str | None, row.get("type")),
        )
        registry[entity.id] = entity
        entities_loaded += 1

    if events_path.exists():
        for row in _iter_jsonl(events_path):
            event_id = cast(str, row["id"])
            event, created = _ensure_entity(
                registry,
                event_id,
                raw_type="event",
                canonical=cast(str, row.get("description", event_id)),
            )
            if created:
                events_loaded += 1
            elif isinstance(event, Event):
                # Keep existing event from another source if already present.
                events_loaded += 1

    if moments_path.exists():
        for row in _iter_jsonl(moments_path):
            moment_id = cast(str, row["id"])
            moment, created = _ensure_entity(
                registry,
                moment_id,
                raw_type="moment",
                canonical=cast(str, row.get("label", moment_id)),
            )
            if created:
                moments_loaded += 1
            elif isinstance(moment, Moment):
                moments_loaded += 1

    statements: list[StoryStatement[Any, Any]] = []

    for row in _iter_jsonl(triplets_path):
        extraction_confidence = cast(float | None, row.get("extraction_confidence"))
        if (
            confidence_threshold is not None
            and extraction_confidence is not None
            and extraction_confidence < confidence_threshold
        ):
            skipped_low_confidence += 1
            continue

        predicate_name = cast(str, row["predicate"])
        predicate_cls = _PREDICATE_MAP.get(predicate_name)
        if predicate_cls is None:
            unknown_predicates.add(predicate_name)
            continue

        subject_id = cast(str, row["subject_id"])
        object_id = cast(str, row["object_id"])

        subject, subject_created = _ensure_entity(
            registry,
            subject_id,
            raw_type=cast(str | None, row.get("subject_type")),
        )
        object_, object_created = _ensure_entity(
            registry,
            object_id,
            raw_type=cast(str | None, row.get("object_type")),
        )
        if subject_created:
            placeholders_created += 1
        if object_created:
            placeholders_created += 1

        raw_truth = cast(str, row.get("truth_status", "hypothetical"))
        truth_status = cast(TruthStatus, raw_truth)

        raw_method = cast(str | None, row.get("extraction_method"))
        provenance = Provenance(
            source=f"{triplets_path.name}:{cast(str, row['id'])}:{raw_method or 'unknown'}",
            extraction_method=_coerce_extraction_method(raw_method),
        )

        sentence_ids_raw = cast(list[int] | None, row.get("sentence_ids"))
        sentence_ids = tuple(sentence_ids_raw or [])

        stmt = predicate_cls(
            id=cast(str, row["id"]),
            subject=subject,
            object_=object_,
            truth_status=truth_status,
            provenance=(provenance,),
            story_id=cast(str, row.get("story_id", story_prefix)),
            paragraph_index=cast(int | None, row.get("paragraph_index")),
            sentence_ids=sentence_ids,
            asserting_narrator_id=cast(str | None, row.get("asserting_narrator_id")),
            extraction_confidence=extraction_confidence,
            narrator_confidence=cast(float | None, row.get("narrator_confidence")),
            raw_extraction_method=raw_method,
        )
        statements.append(stmt)
        statements_loaded += 1

    existing_statement_ids = {stmt.id for stmt in statements}
    for event_id, location_id in _EVENT_LOCATION_HINTS.items():
        event_inst = registry.get(event_id)
        location_inst = registry.get(location_id)
        if not isinstance(event_inst, Event) or not isinstance(location_inst, Location):
            continue

        stmt_id = f"stmt:{event_id}:HappenedIn:{location_id}"
        if stmt_id in existing_statement_ids:
            continue

        statements.append(
            HappenedIn(
                id=stmt_id,
                subject=event_inst,
                object_=location_inst,
                truth_status="asserted_true",
                provenance=(
                    Provenance(
                        source=(
                            f"{triplets_path.name}:{stmt_id}:"
                            "importer-event-location-hint"
                        ),
                        extraction_method="inferred",
                    ),
                ),
                story_id=story_prefix,
                raw_extraction_method="importer-event-location-hint",
            )
        )
        existing_statement_ids.add(stmt_id)
        statements_loaded += 1

    graph = Graph()
    graph.extend(registry.values())
    graph.extend(statements)

    report = ImportReport(
        entities_loaded=entities_loaded,
        events_loaded=events_loaded,
        moments_loaded=moments_loaded,
        statements_loaded=statements_loaded,
        placeholders_created=placeholders_created,
        skipped_low_confidence=skipped_low_confidence,
        unknown_predicates=tuple(sorted(unknown_predicates)),
    )
    return graph, report
