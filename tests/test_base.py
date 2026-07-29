"""Trait declarations on predicate types: marker introspection and Inverse."""

import pytest
from pydantic import ValidationError

from base import (
    BaseStatement,
    Functional,
    Inverse,
    InverseFunctional,
    Provenance,
    Symmetric,
    Transitive,
    get_inverse,
)
from example import Knows, Person, WorksFor, alice, bob


class ReportsTo(BaseStatement[Person, Person], Transitive, Functional):
    """Transitive and functional."""


class Marries(BaseStatement[Person, Person], Symmetric, InverseFunctional):
    """Symmetric and inverse-functional (at most one spouse per person)."""


class ParentOf(BaseStatement[Person, Person]):
    """ParentOf(x, y): x is a parent of y."""


class ChildOf(BaseStatement[Person, Person], Inverse[ParentOf]):
    """The inverse of ParentOf."""


class Ancestor(BaseStatement[Person, Person], Inverse["Descendant"]):
    """Declares its inverse as a forward reference (Descendant is defined below)."""


class Descendant(BaseStatement[Person, Person]):
    """The predicate Ancestor names as its (forward-referenced) inverse."""


def test_trait_mixin_does_not_break_construction() -> None:
    k = Knows(id="k1", subject=alice, object_=bob)
    assert k.subject.name == "Alice"
    assert k.truth_status == "hypothetical"


def test_marker_traits_are_introspectable() -> None:
    assert issubclass(Knows, Symmetric)
    assert not issubclass(WorksFor, Symmetric)


def test_a_predicate_may_carry_several_traits() -> None:
    assert issubclass(ReportsTo, Transitive)
    assert issubclass(ReportsTo, Functional)
    assert not issubclass(ReportsTo, Symmetric)


def test_inverse_functional_marker() -> None:
    assert issubclass(Marries, InverseFunctional)
    assert issubclass(Marries, Symmetric)
    assert not issubclass(WorksFor, InverseFunctional)


def test_get_inverse_resolves_declared_partner() -> None:
    assert get_inverse(ChildOf) is ParentOf


def test_get_inverse_resolves_forward_reference() -> None:
    assert get_inverse(Ancestor) is Descendant


def test_get_inverse_is_none_without_the_trait() -> None:
    assert get_inverse(WorksFor) is None
    assert get_inverse(ParentOf) is None


def test_inverse_with_mismatched_domain_range_raises_at_definition() -> None:
    # WorksFor is Person -> Organization; a correct inverse must be
    # Organization -> Person. Declaring Person -> Person is a type error.
    with pytest.raises(TypeError, match="not the swap"):

        class BadInverse(BaseStatement[Person, Person], Inverse[WorksFor]):
            pass


def test_extraction_method_is_a_closed_vocabulary() -> None:
    # "manual" is valid; an unlisted method is rejected.
    Provenance(source="doc", extraction_method="manual")
    with pytest.raises(ValidationError):
        Provenance(source="doc", extraction_method="guessed")  # type: ignore[arg-type]
