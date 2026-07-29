"""Domain/range enforcement in the class-per-type (generic) model.

Static enforcement (mypy) is the primary guarantee here and is verified
separately; these tests cover the runtime behavior that backs it up.
"""

import pytest
from pydantic import ValidationError

from base import BaseStatement, Instance, Provenance, Symmetric, get_inverse
from example import (
    Believes,
    Employs,
    Knows,
    Organization,
    Owns,
    Person,
    WorksFor,
    acme,
    alice,
    car,
)


def test_valid_statement_builds() -> None:
    prov = Provenance(source="hr.csv", extraction_method="manual")
    rel = WorksFor(
        id="alice-works_for-acme",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov,),
    )
    assert rel.subject.name == "Alice"
    assert rel.object_.industry == "widgets"
    assert rel.provenance == (prov,)  # grounded


def test_statement_is_a_member_of_V() -> None:
    # E subset of V: a statement is an Instance, just like an entity instance.
    rel = WorksFor(id="r", subject=alice, object_=acme)
    assert isinstance(rel, Instance)
    assert isinstance(alice, Instance)


def test_wrong_subject_type_rejected_at_runtime() -> None:
    # subject must be a Person; passing an Organization must fail.
    with pytest.raises(ValidationError):
        WorksFor(id="bad", subject=acme, object_=acme)  # type: ignore[arg-type]


def test_statement_defaults_to_ungrounded_hypothetical() -> None:
    rel = WorksFor(id="r2", subject=alice, object_=acme)
    assert rel.provenance is None  # ungrounded
    assert rel.truth_status == "hypothetical"


def test_union_domain_accepts_every_member() -> None:
    # dom(Owns) = {Person, Organization}: both are valid subjects.
    person_owns = Owns(id="o1", subject=alice, object_=car)
    org_owns = Owns(id="o2", subject=acme, object_=car)
    assert isinstance(person_owns.subject, Person)
    assert isinstance(org_owns.subject, Organization)


def test_union_domain_rejects_a_type_outside_the_set() -> None:
    # A Vehicle is in the range but not the domain of Owns.
    with pytest.raises(ValidationError):
        Owns(id="bad", subject=car, object_=car)  # type: ignore[arg-type]


def test_example_inverse_pair_resolves() -> None:
    assert get_inverse(Employs) is WorksFor
    assert get_inverse(WorksFor) is None


def test_example_symmetric_trait() -> None:
    assert issubclass(Knows, Symmetric)
    assert not issubclass(WorksFor, Symmetric)


def test_higher_order_object_is_a_statement() -> None:
    # E subset of V: a statement may be the object_ of another statement.
    inner = WorksFor(id="w1", subject=alice, object_=acme)
    outer = Believes(id="b1", subject=alice, object_=inner)
    assert isinstance(outer.object_, BaseStatement)


def test_higher_order_preserves_concrete_predicate_type() -> None:
    # The AnyStatement range keeps the object's concrete predicate type (tau):
    # it is the same WorksFor instance, not a downcast BaseStatement.
    inner = WorksFor(id="w1", subject=alice, object_=acme)
    outer = Believes(id="b1", subject=alice, object_=inner)
    assert isinstance(outer.object_, WorksFor)
    assert outer.object_ is inner
