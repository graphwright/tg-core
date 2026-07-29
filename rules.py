"""Horn-clause rules for Python-native deduction, and the rule/deduction
exceptions. The engine is in datalog.py.

Rules are built directly in Python -- no text grammar:

    x, y, z = variables("x y z")
    transitivity = Rule(lit(Ancestor, x, z), (lit(Ancestor, x, y), lit(Ancestor, y, z)))

- `Var` is a named, untyped logic variable (`variables("x y z")`).
- `Literal` pairs a predicate *class* with two arguments, each a `Var` or a
  concrete entity `Instance`; `lit(Pred, a, b)` is the constructor.
- `Rule(head, body)` is a Horn clause.

Type safety is deferred to derivation time: the engine constructs each derived
head through the predicate class, so Pydantic validates domain/range then. That
is why variables need no static type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from base import AnyStmt, BaseStatement, Instance

# --------------------------------------------------------------------------- #
# Exceptions (the gotchas, made loud)
# --------------------------------------------------------------------------- #


class RuleError(Exception):
    """Base class for rule / deduction errors."""


class UnsafeRuleError(RuleError):
    """Range restriction violated: a variable in the head does not appear in any
    body literal, so the conclusion cannot be grounded."""


class UnsupportedRuleError(RuleError):
    """A construct outside v1 Datalog: a higher-order literal (an argument that is
    itself a statement), a higher-order fact, or a trait the engine cannot compile
    to a derivation rule (Functional / InverseFunctional)."""


class FixpointError(RuleError):
    """Derivation exceeded the iteration bound. Datalog over a finite domain must
    terminate; this is a backstop against a bug (e.g. non-idempotent ids), not an
    expected condition."""


# --------------------------------------------------------------------------- #
# Variables, literals, rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, repr=False)
class Var:
    """A named, untyped logic variable. Its type is whatever the predicate
    positions it occupies require, checked when a derived fact is constructed."""

    name: str

    def __repr__(self) -> str:
        return f"?{self.name}"


def variables(names: str) -> tuple[Var, ...]:
    """variables("x y z") -> (Var('x'), Var('y'), Var('z'))."""
    return tuple(Var(n) for n in names.split())


def variable(name: str) -> Var:
    """A single variable: variable("x") -> Var('x')."""
    return Var(name)


Arg = Union[Var, Instance]


@dataclass(frozen=True, repr=False)
class Literal:
    """A predicate applied to two arguments (each a Var or concrete Instance).
    A rule *pattern* -- unlike a BaseStatement it is not a member of V."""

    predicate: type[AnyStmt]
    args: tuple[Arg, Arg]

    def __repr__(self) -> str:
        return (
            f"{self.predicate.__name__}"
            f"({_arg_repr(self.args[0])}, {_arg_repr(self.args[1])})"
        )


def _arg_repr(arg: Arg) -> str:
    return repr(arg) if isinstance(arg, Var) else arg.id


def lit(predicate: type[AnyStmt], subject: Arg, object_: Arg) -> Literal:
    """Build a rule literal: lit(WorksFor, x, y)."""
    return Literal(predicate, (subject, object_))


@dataclass(frozen=True, repr=False)
class Rule:
    """A Horn clause: derive `head` when every literal in `body` holds."""

    head: Literal
    body: tuple[Literal, ...]

    def __repr__(self) -> str:
        return f"{self.head!r} :- {', '.join(repr(lt) for lt in self.body)}"


def validate_rule(rule: Rule) -> None:
    """Reject unsupported constructs and enforce range restriction.

    Raises UnsupportedRuleError if any literal has a statement-valued argument
    (higher-order rules are deferred). Raises UnsafeRuleError if a head variable
    is absent from the body.
    """
    for literal in (rule.head, *rule.body):
        for arg in literal.args:
            if isinstance(arg, BaseStatement):
                raise UnsupportedRuleError(
                    f"literal {literal!r} has a statement argument; higher-order "
                    "rules are not supported"
                )
    body_vars = {a.name for lt in rule.body for a in lt.args if isinstance(a, Var)}
    head_vars = {a.name for a in rule.head.args if isinstance(a, Var)}
    unbound = head_vars - body_vars
    if unbound:
        raise UnsafeRuleError(
            f"head variable(s) {sorted(unbound)} of {rule.head!r} do not appear "
            "in the body (range restriction)"
        )
