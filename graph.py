"""graph.py — in-memory typed graph over BaseStatement/EntityInstance objects.

No database, no MCP server. Load a set of instances, build indexes, run
BFS and named queries directly against the Python objects.

Typical usage:

    import example
    from graph import Graph

    g = Graph.from_module(example)
    g.bfs(['alice'], max_hops=2)
"""

from __future__ import annotations

import warnings
from collections import defaultdict
from collections.abc import Iterable, Sequence
from types import ModuleType
from typing import Any, TypeAlias, TypeGuard

from base import BaseStatement, Instance, TruthStatus

"""
## Helpers

Duck-typed predicates used during graph construction. Avoiding a direct
import of `EntityInstance` and `BaseStatement` keeps `graph.py` decoupled
from the schema module — any object that has the right attributes will be
indexed correctly.
"""


_WIKI_PREFIX = "https://bakerstreet.fandom.com/wiki/"

AnyStmt: TypeAlias = BaseStatement[Any, Any]
PredicateType: TypeAlias = type[AnyStmt]
TruthSelector: TypeAlias = TruthStatus | Iterable[TruthStatus]


def _canonicalize_id(entity_id: str) -> str:
    if entity_id.startswith(_WIKI_PREFIX):
        return "wiki:" + entity_id[len(_WIKI_PREFIX) :]
    return entity_id


def _is_entity(obj: object) -> TypeGuard[Instance]:
    return isinstance(obj, Instance)


def _is_statement(obj: object) -> TypeGuard[AnyStmt]:
    return isinstance(obj, BaseStatement)


"""
## Graph

`Graph` is an in-memory knowledge graph indexed for O(1) neighbor lookup.
Instances are bucketed into three indexes: `by_id` for direct access,
`out_edges` keyed by `subject.id` for forward traversal, and `in_edges`
keyed by `object_.id` for backward traversal.

Because predicate instances are also entities under the unified Statement
model, they are indexed in `by_id` and can themselves appear as the
subject or object of higher-order predicates.
"""


class Graph:
    def __init__(self, instances: Iterable[object] = ()):
        self.by_id: dict[str, Instance] = {}
        self.out_edges: dict[str, list[AnyStmt]] = defaultdict(
            list
        )  # subject.id -> [stmt]
        self.in_edges: dict[str, list[AnyStmt]] = defaultdict(
            list
        )  # object_.id -> [stmt]

        self.extend(instances)

    def add(self, instance: object) -> None:
        """Insert one entity or statement instance into the graph indexes.

        Non-instance objects are ignored so callers can pass mixed collections.
        """
        if not _is_entity(instance):
            return

        if instance.id in self.by_id:
            warnings.warn(
                f"Graph: id collision on {instance.id!r} — overwriting; "
                "use unique ids per extraction or statement_id() for canonical facts",
                stacklevel=2,
            )
        self.by_id[instance.id] = instance
        if _is_statement(instance):
            self.out_edges[instance.subject.id].append(instance)
            self.in_edges[instance.object_.id].append(instance)

    def extend(self, instances: Iterable[object]) -> None:
        """Insert many instances by repeatedly applying `add()`."""
        for inst in instances:
            self.add(inst)

    @classmethod
    def from_module(cls, module: ModuleType) -> Graph:
        """Build a Graph from all EntityInstance values in a module's namespace."""
        return cls(
            v
            for v in vars(module).values()
            if _is_entity(v) and not isinstance(v, type)
        )

    def get(self, entity_id: str) -> Instance | None:
        """Return the instance for entity_id, normalizing wiki URLs to canonical form."""
        return self.by_id.get(_canonicalize_id(entity_id))

    def edges_from(
        self,
        entity_id: str,
        pred_type: PredicateType | tuple[PredicateType, ...] | None = None,
        truth: TruthSelector | None = None,
    ) -> list[AnyStmt]:
        """Outward edges from entity_id, optionally filtered by type and truth_status."""
        edges = self.out_edges.get(_canonicalize_id(entity_id), [])
        if pred_type is not None:
            edges = [e for e in edges if isinstance(e, pred_type)]
        if truth is not None:
            truth_set = {truth} if isinstance(truth, str) else set(truth)
            edges = [e for e in edges if e.truth_status in truth_set]
        return edges

    def edges_to(
        self,
        entity_id: str,
        pred_type: PredicateType | tuple[PredicateType, ...] | None = None,
        truth: TruthSelector | None = None,
    ) -> list[AnyStmt]:
        """Inward edges to entity_id, optionally filtered by type and truth_status."""
        edges = self.in_edges.get(_canonicalize_id(entity_id), [])
        if pred_type is not None:
            edges = [e for e in edges if isinstance(e, pred_type)]
        if truth is not None:
            truth_set = {truth} if isinstance(truth, str) else set(truth)
            edges = [e for e in edges if e.truth_status in truth_set]
        return edges

    def bfs(
        self,
        seed_ids: list[str],
        max_hops: int = 3,
        pred_types: Sequence[PredicateType] | None = None,
        truth_values: tuple[TruthStatus, ...] = ("asserted_true",),
    ) -> list[set[str]]:
        """BFS from seed_ids. Returns one set per hop layer.

        Traverses both outward and inward edges so symmetric predicates (e.g.
        Knows) and reverse relationships (e.g. Events that Involve a person)
        are reachable regardless of the direction they were stored. The
        traversed statement instances are also added to layers so higher-order
        predicates can be followed in later hops.
        """
        visited: set[str] = set(seed_ids)
        frontier: set[str] = set(seed_ids)
        layers: list[set[str]] = [set(seed_ids)]
        pred_type_tuple: tuple[PredicateType, ...] | None = (
            tuple(pred_types) if pred_types is not None else None
        )

        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for eid in frontier:
                for edge in self.out_edges.get(eid, []):
                    if pred_type_tuple is not None and not isinstance(
                        edge, pred_type_tuple
                    ):
                        continue
                    if edge.truth_status not in truth_values:
                        continue
                    for nid in (edge.object_.id, edge.id):
                        if nid not in visited:
                            visited.add(nid)
                            next_frontier.add(nid)
                for edge in self.in_edges.get(eid, []):
                    if pred_type_tuple is not None and not isinstance(
                        edge, pred_type_tuple
                    ):
                        continue
                    if edge.truth_status not in truth_values:
                        continue
                    for nid in (edge.subject.id, edge.id):
                        if nid not in visited:
                            visited.add(nid)
                            next_frontier.add(nid)
            layers.append(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        return layers

    def transitive_closure(
        self,
        entity_id: str,
        pred_type: PredicateType,
        truth_values: tuple[TruthStatus, ...] = ("asserted_true",),
    ) -> set[str]:
        """All entities reachable from entity_id by following pred_type transitively."""
        visited: set[str] = set()
        frontier: set[str] = {entity_id}
        while frontier:
            next_f: set[str] = set()
            for eid in frontier:
                for edge in self.out_edges.get(eid, []):
                    if not isinstance(edge, pred_type):
                        continue
                    if edge.truth_status not in truth_values:
                        continue
                    obj_id = edge.object_.id
                    if obj_id not in visited:
                        visited.add(obj_id)
                        next_f.add(obj_id)
            frontier = next_f
        return visited

    def describe(self, entity_id: str) -> str:
        """Human-readable description of an instance by id."""
        inst = self.get(entity_id)
        if inst is None:
            return f"<not found: {entity_id}>"
        return str(inst)

    def print_edges(self, edges: Iterable[AnyStmt], indent: int = 2) -> None:
        pad = " " * indent
        for e in edges:
            print(f"{pad}{e}  [{e.truth_status}]")
