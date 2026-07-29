"""Scenario-level probabilistic primitives for *A Scandal in Bohemia*.

Step 3 in the ProbLog plan is to identify a small set of independent random
variables (coin flips) that can explain observed events. This module defines a
first curated set for the photograph-location mystery.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from base import BaseStatement
from graph import Graph
from pydantic import BaseModel, ConfigDict, Field


class PrimitiveRandomVariable(BaseModel):
    """One independent Bernoulli variable in ProbLog notation."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    probability: float = Field(ge=0.0, le=1.0)
    rationale: str

    def to_problog(self) -> str:
        """Render this primitive as an annotated ProbLog fact."""
        return f"{self.probability:.6f}::{self.symbol}."


SCANDAL_PRIMITIVES: tuple[PrimitiveRandomVariable, ...] = (
    PrimitiveRandomVariable(
        symbol="photo_is_real",
        probability=0.99,
        rationale="The compromising photograph exists and matters strategically.",
    ),
    PrimitiveRandomVariable(
        symbol="irene_alarm_response",
        probability=0.85,
        rationale="In an alarm scenario, Irene acts to secure highest-value leverage.",
    ),
    PrimitiveRandomVariable(
        symbol="trusts_clergyman_disguise",
        probability=0.70,
        rationale="Irene and bystanders accept Holmes's clergyman role as non-threat.",
    ),
    PrimitiveRandomVariable(
        symbol="protective_instinct_for_injured",
        probability=0.80,
        rationale="The crowd and host prioritize sheltering an apparently injured person.",
    ),
)


def scandal_primitive_lines(
    primitives: Sequence[PrimitiveRandomVariable] = SCANDAL_PRIMITIVES,
) -> list[str]:
    """Annotated fact lines for the current Scandal primitive set."""
    return [primitive.to_problog() for primitive in primitives]


def scandal_explanatory_rules() -> list[str]:
    """Deterministic links from primitives to scenario-level latent events.

    These are not observations/evidence yet; they define how primitive coin
    flips combine into latent hypotheses for later conditioning.
    """
    return [
        "alarm_reveal_moment :- photo_is_real, irene_alarm_response.",
        (
            "carry_event_feasible :- "
            "trusts_clergyman_disguise, protective_instinct_for_injured."
        ),
    ]


class EvidenceObservation(BaseModel):
    """One observable fact used as ProbLog conditioning evidence."""

    model_config = ConfigDict(frozen=True)

    predicate_symbol: str
    subject_id: str
    object_id: str
    rationale: str

    def to_problog(self) -> str:
        """Render this observation as ProbLog evidence(true)."""
        return (
            "evidence("
            f"{self.predicate_symbol}({_quote(self.subject_id)}, {_quote(self.object_id)}), true"
            ")."
        )


SCANDAL_EVIDENCE: tuple[EvidenceObservation, ...] = (
    EvidenceObservation(
        predicate_symbol="occurred_at",
        subject_id="sib:event:holmes_carried_into_sitting_room",
        object_id="sib:moment:holmes_learns_photograph_location",
        rationale="Holmes being carried in happens at the reveal moment.",
    ),
    EvidenceObservation(
        predicate_symbol="occurred_at",
        subject_id="sib:event:adler_rushes_to_photograph",
        object_id="sib:moment:holmes_learns_photograph_location",
        rationale="Irene rushing to the photograph happens at the same reveal moment.",
    ),
    EvidenceObservation(
        predicate_symbol="happened_in",
        subject_id="sib:event:holmes_carried_into_sitting_room",
        object_id="place:irene_adlers_sitting-room",
        rationale="The carry event is structurally tied to the sitting room.",
    ),
)


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


def _quote(term: str) -> str:
    return json.dumps(term)


def _supports_observation(graph: Graph, obs: EvidenceObservation) -> bool:
    """Return true when an asserted statement in graph matches this observation."""
    for inst in graph.by_id.values():
        if not isinstance(inst, BaseStatement):
            continue
        stmt = inst
        if stmt.truth_status != "asserted_true":
            continue
        if _camel_to_snake(type(stmt).__name__) != obs.predicate_symbol:
            continue
        if stmt.subject.id != obs.subject_id:
            continue
        if stmt.object_.id != obs.object_id:
            continue
        return True
    return False


def scandal_evidence_lines(
    graph: Graph | None = None,
    observations: Sequence[EvidenceObservation] = SCANDAL_EVIDENCE,
) -> list[str]:
    """Evidence lines for the Scandal mystery.

    If ``graph`` is provided, emit only observations supported by asserted graph
    facts so evidence cannot silently drift away from imported structure.
    """
    if graph is None:
        return [obs.to_problog() for obs in observations]
    return [
        obs.to_problog() for obs in observations if _supports_observation(graph, obs)
    ]


def scandal_ranking_rules(
    *,
    owner_id: str = "wiki:Irene_Adler",
    carry_event_id: str = "sib:event:holmes_carried_into_sitting_room",
    reveal_moment_id: str = "sib:moment:holmes_learns_photograph_location",
    reveal_event_id: str = "sib:event:adler_rushes_to_photograph",
) -> list[str]:
    """Rules that turn evidence and primitives into rankable place hypotheses."""
    return [
        f"candidate_place(Place) :- associated_with({_quote(owner_id)}, Place).",
        (
            "reveal_coincidence_place(Place) :- "
            f"happened_in({_quote(carry_event_id)}, Place), "
            f"occurred_at({_quote(carry_event_id)}, {_quote(reveal_moment_id)}), "
            f"occurred_at({_quote(reveal_event_id)}, {_quote(reveal_moment_id)})."
        ),
        "0.350000::photo_in_place(Place) :- candidate_place(Place), photo_is_real.",
        (
            "0.980000::photo_in_place(Place) :- "
            "reveal_coincidence_place(Place), alarm_reveal_moment, carry_event_feasible."
        ),
    ]
