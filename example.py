"""Worked domain for the typed graph base package.

Entity types: Person, Organization, Vehicle.
Predicate types: WorksFor, Employs (its inverse), Owns (a `|`-union domain),
and Knows (symmetric).

The runnable `main()` demonstrates the mutable graph API:

    g = Graph()
    g.add(alice)
    g.add(acme)
    g.add(works_for)
"""

from base import (
    AnyStatement,
    BaseStatement,
    EntityInstance,
    Inverse,
    Provenance,
    Symmetric,
)
from graph import Graph
from serialize import to_python


class Person(EntityInstance):
    """An individual person."""

    name: str


class Organization(EntityInstance):
    """A company or other organization."""

    name: str
    industry: str


class Vehicle(EntityInstance):
    """A vehicle that a Person or Organization may own."""

    make: str


class WorksFor(BaseStatement[Person, Organization]):
    """dom = {Person}, ran = {Organization}."""


class Employs(BaseStatement[Organization, Person], Inverse[WorksFor]):
    """dom = {Organization}, ran = {Person}. The inverse of WorksFor:
    WorksFor(p, o) implies Employs(o, p)."""


class Owns(BaseStatement[Person | Organization, Vehicle]):
    """A multi-member domain, written as a `|` union -- the union *is* the set:
    dom = {Person, Organization}, ran = {Vehicle}. Either an individual or an
    organization may own a vehicle."""


class Knows(BaseStatement[Person, Person], Symmetric):
    """dom = ran = {Person}. Symmetric: Knows(x, y) implies Knows(y, x)."""


class Believes(BaseStatement[Person, AnyStatement]):
    """Higher-order: dom = {Person}, ran = any statement. Believes(p, s) says
    person p believes statement s; s keeps its concrete predicate type."""


# Sample entity instances. Instances are frozen, so these are safe to share.
alice = Person(id="alice", name="Alice")
bob = Person(id="bob", name="Bob")
acme = Organization(id="acme", name="Acme Corp", industry="widgets")
car = Vehicle(id="car1", make="Toyota")


def main() -> None:
    g = Graph()
    g.add(alice)
    g.add(acme)
    g.extend([bob, car])

    prov = Provenance(source="hr.csv", extraction_method="manual")
    works_for = WorksFor(
        id="alice-works_for-acme",
        subject=alice,
        object_=acme,
        truth_status="asserted_true",
        provenance=(prov,),
    )
    g.add(works_for)

    outer = Believes(id="belief", subject=alice, object_=works_for)
    g.add(outer)

    assert isinstance(outer, BaseStatement)
    assert isinstance(outer.object_, BaseStatement)
    assert g.get("alice") is alice
    assert g.edges_from("alice", pred_type=WorksFor) == [works_for]

    print(g.describe("alice"))
    print(to_python([outer]))


if __name__ == "__main__":
    # Import from the module so all types carry __module__ == "example"
    # (serialize.to_python requires importable types, not __main__).
    from example import main as _main

    _main()
