"""Naive bottom-up Datalog deduction engine.

Fixed-point evaluation over the asserted graph:

1. Seed with ground facts (truth_status == asserted_true).
2. Each round, match every rule's body against the known facts -- a k-way join
   on shared variables.
3. Instantiate the head under each binding, constructing it *through the
   predicate class* so Pydantic re-validates domain/range (R6).
4. Repeat until a round derives nothing new (the least fixed point).

Convergence is guaranteed because the entity set is finite and facts are deduped
by a content-addressed key ``Functor(subjId,objId)``; that key is also the
derived fact's id, so re-deriving a fact maps to the same entry and never
re-fires. Seed facts keep whatever id they were built with; when multiple
asserted or derived facts corroborate the same key, the engine merges their
provenance records onto the first-seen fact instead of dropping or rejecting it.

Derived facts are grounded: ``extraction_method="inferred"`` and
``source=repr(rule)``, so a suspect derived fact points back at the rule that
produced it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from base import (
    AnyStmt,
    BaseStatement,
    Functional,
    Instance,
    InverseFunctional,
    Provenance,
    Symmetric,
    Transitive,
    get_inverse,
)
from rules import (
    Arg,
    FixpointError,
    Literal,
    Rule,
    UnsupportedRuleError,
    Var,
    lit,
    validate_rule,
    variables,
)


class Engine:
    """Naive bottom-up fixed-point Datalog evaluator."""

    def __init__(self, max_iterations: int = 100) -> None:
        self._rules: list[Rule] = []
        # content-addressed key Functor(subjId,objId) -> statement; owns dedup
        self._known: dict[str, AnyStmt] = {}
        # predicate -> [(subj_id, obj_id)] for full scans
        self._facts_by_pred: dict[type, list[tuple[str, str]]] = {}
        # (predicate, subj_id) -> [obj_id]; fast path when the subject is bound
        self._facts_by_pred_subj: dict[tuple[type, str], list[str]] = {}
        # id -> Instance; holds only entities (higher-order facts are rejected)
        self._instance_index: dict[str, Instance] = {}
        self._max_iterations = max_iterations

    @staticmethod
    def _key(predicate: type[AnyStmt], subj_id: str, obj_id: str) -> str:
        return f"{predicate.__module__}.{predicate.__qualname__}({subj_id},{obj_id})"

    # ---------------------------------------------------------------------- #
    # Population
    # ---------------------------------------------------------------------- #

    def add_facts(self, facts: Iterable[AnyStmt]) -> int:
        """Seed the engine with ground facts; only truth_status == asserted_true
        is reasoned over. Raises UnsupportedRuleError for a higher-order fact (an
        asserted statement whose object is itself a statement). Return the
        number of statements ignored because their status is not asserted_true."""
        skipped = 0
        seen: dict[str, AnyStmt] = {}
        for stmt in facts:
            if isinstance(stmt.object_, BaseStatement):
                raise UnsupportedRuleError(
                    f"higher-order fact {type(stmt).__name__}: its object is a "
                    "statement; higher-order reasoning is not supported"
                )
            if stmt.truth_status != "asserted_true":
                skipped += 1
                continue
            key = self._key(type(stmt), stmt.subject.id, stmt.object_.id)
            existing = seen.get(key)
            if existing is None:
                existing = self._known.get(key)
            if existing is None:
                seen[key] = stmt
            else:
                seen[key] = self._merge_duplicate(key, existing, stmt)
        for stmt in seen.values():
            self._register_fact(stmt)
        return skipped

    @staticmethod
    def _merge_provenance(
        base_provenance: tuple[Provenance, ...] | None,
        additional_provenance: tuple[Provenance, ...] | None,
    ) -> tuple[Provenance, ...] | None:
        """Merge provenance tuples, preserving order and deduplicating by equality."""
        if base_provenance is None:
            return additional_provenance
        if additional_provenance is None:
            return base_provenance
        merged = list(base_provenance)
        # Provenance is a frozen Pydantic model, so records are hashable and can
        # be tracked in a set while preserving insertion order in `merged`.
        seen = set(base_provenance)
        for prov in additional_provenance:
            if prov not in seen:
                merged.append(prov)
                seen.add(prov)
        return tuple(merged)

    def _merge_duplicate(
        self, key: str, existing: AnyStmt, incoming: AnyStmt
    ) -> AnyStmt:
        if existing.truth_status != incoming.truth_status:
            raise ValueError(
                "conflicting duplicate fact for content-addressed key "
                f"{key!r}: truth_status {existing.truth_status!r} != "
                f"{incoming.truth_status!r}"
            )
        merged_provenance = self._merge_provenance(
            existing.provenance, incoming.provenance
        )
        if merged_provenance == existing.provenance:
            return existing
        return existing.model_copy(update={"provenance": merged_provenance})

    def _merge_provenance_record(
        self, stmt: AnyStmt, provenance: Provenance
    ) -> AnyStmt:
        if stmt.provenance is None:
            return stmt.model_copy(update={"provenance": (provenance,)})
        if provenance in stmt.provenance:
            return stmt
        return stmt.model_copy(update={"provenance": (*stmt.provenance, provenance)})

    def _register_fact(self, stmt: AnyStmt) -> None:
        predicate = type(stmt)
        subj_id, obj_id = stmt.subject.id, stmt.object_.id
        key = self._key(predicate, subj_id, obj_id)
        existing = self._known.get(key)
        if existing is not None:
            # Duplicate merges only change instance metadata (currently provenance),
            # so the predicate/subject/object indexes remain valid.
            self._known[key] = self._merge_duplicate(key, existing, stmt)
            return
        self._known[key] = stmt
        self._facts_by_pred.setdefault(predicate, []).append((subj_id, obj_id))
        self._facts_by_pred_subj.setdefault((predicate, subj_id), []).append(obj_id)
        self._instance_index[subj_id] = stmt.subject
        self._instance_index[obj_id] = stmt.object_

    def add_rule(self, rule: Rule) -> None:
        """Validate and register a rule (raises UnsafeRuleError /
        UnsupportedRuleError -- see rules.validate_rule)."""
        validate_rule(rule)
        self._rules.append(rule)

    def add_traits(self, *predicate_types: type[AnyStmt]) -> None:
        """Compile the derivation traits (Transitive, Symmetric, Inverse) of each
        predicate into rules.

        Raises UnsupportedRuleError for a predicate declaring Functional or
        InverseFunctional: those are integrity constraints, not derivations, and
        the engine has no constraint checker yet -- failing loudly beats silently
        ignoring them.
        """
        x, y, z = variables("x y z")
        for pred in predicate_types:
            if issubclass(pred, (Functional, InverseFunctional)):
                raise UnsupportedRuleError(
                    f"{pred.__name__} declares Functional/InverseFunctional, which "
                    "are integrity constraints, not derivations; the engine cannot "
                    "compile them to rules"
                )
            if issubclass(pred, Transitive):
                self.add_rule(Rule(lit(pred, x, z), (lit(pred, x, y), lit(pred, y, z))))
            if issubclass(pred, Symmetric):
                self.add_rule(Rule(lit(pred, y, x), (lit(pred, x, y),)))
            inverse = get_inverse(pred)
            if inverse is not None:
                self.add_rule(Rule(lit(pred, y, x), (lit(inverse, x, y),)))

    # ---------------------------------------------------------------------- #
    # Evaluation
    # ---------------------------------------------------------------------- #

    def infer(self) -> list[AnyStmt]:
        """Run bottom-up fixed-point evaluation; return the newly derived facts.

        Returned statements are snapshots taken at derivation time: later
        provenance merges update the engine's stored facts, not previously
        returned instances.

        Raises FixpointError if not converged within max_iterations (a backstop),
        and lets pydantic.ValidationError propagate if a derived head violates the
        predicate's domain/range (a schema error the caller must fix).
        """
        newly: list[AnyStmt] = []
        for _ in range(self._max_iterations):
            new_facts_by_key: dict[str, AnyStmt] = {}
            for rule in self._rules:
                inferred_provenance = Provenance(
                    source=repr(rule), extraction_method="inferred"
                )
                for binding in self._match_body(list(rule.body), {}):
                    subj = self._resolve(rule.head.args[0], binding)
                    obj = self._resolve(rule.head.args[1], binding)
                    pred = rule.head.predicate
                    key = self._key(pred, subj.id, obj.id)
                    pending = new_facts_by_key.get(key)
                    if pending is not None:
                        new_facts_by_key[key] = self._merge_provenance_record(
                            pending, inferred_provenance
                        )
                        continue
                    existing = self._known.get(key)
                    if existing is not None:
                        self._known[key] = self._merge_provenance_record(
                            existing, inferred_provenance
                        )
                        continue
                    # Construct through the predicate class so Pydantic validates
                    # domain/range. subj/obj are typed Instance while the fields
                    # want the concrete entity subtype; Pydantic checks at runtime.
                    stmt = pred(
                        id=key,
                        subject=subj,
                        object_=obj,
                        truth_status="asserted_true",
                        provenance=(inferred_provenance,),
                    )
                    new_facts_by_key[key] = stmt
            if not new_facts_by_key:
                break
            for stmt in new_facts_by_key.values():
                self._register_fact(stmt)
                newly.append(stmt)
        else:
            raise FixpointError(
                f"fixpoint did not converge after {self._max_iterations} "
                "iterations; this indicates a bug (non-idempotent ids or "
                "unbounded derivation)"
            )
        return newly

    # ---------------------------------------------------------------------- #
    # Matching
    # ---------------------------------------------------------------------- #

    def _match_body(
        self, literals: list[Literal], bindings: dict[str, str]
    ) -> Iterator[dict[str, str]]:
        """Yield every variable substitution (var name -> entity id) satisfying
        all `literals` against the current facts."""
        if not literals:
            yield dict(bindings)
            return
        literal, rest = literals[0], literals[1:]
        pred = literal.predicate
        subj_arg, obj_arg = literal.args
        subj_bound = self._bound_id(subj_arg, bindings)
        if subj_bound is not None:
            pairs = [
                (subj_bound, o)
                for o in self._facts_by_pred_subj.get((pred, subj_bound), [])
            ]
        else:
            pairs = self._facts_by_pred.get(pred, [])
        for subj_id, obj_id in pairs:
            extended = dict(bindings)
            if self._unify(subj_arg, subj_id, extended) and self._unify(
                obj_arg, obj_id, extended
            ):
                yield from self._match_body(rest, extended)

    @staticmethod
    def _bound_id(arg: Arg, bindings: dict[str, str]) -> str | None:
        """The id an argument is already fixed to (a bound var or a constant), or
        None for an unbound variable."""
        if isinstance(arg, Var):
            return bindings.get(arg.name)
        return arg.id  # Instance constant

    @staticmethod
    def _unify(arg: Arg, val: str, bindings: dict[str, str]) -> bool:
        if isinstance(arg, Var):
            if arg.name in bindings:
                return bindings[arg.name] == val
            bindings[arg.name] = val
            return True
        return arg.id == val  # Instance constant must match exactly

    def _resolve(self, arg: Arg, bindings: dict[str, str]) -> Instance:
        """Resolve a head argument to the Instance to place in the derived fact."""
        if isinstance(arg, Var):
            return self._instance_index[bindings[arg.name]]
        if isinstance(arg, BaseStatement):
            raise AssertionError(
                "statement constant in head; higher-order rules are rejected by "
                "add_rule"
            )
        return arg  # Instance constant
