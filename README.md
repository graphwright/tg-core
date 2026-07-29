# Informal typed graph specification

The formal definition of a typed graph appears in the file `formal-defns.md`.
The intention here is to define an informal definition that will be
comfortable for Python developers, framed as a base package that can be
extended to accomodate different knowledge domains.

The 4-tuple $(T, \Phi, V, \tau)$ is realized as a small Pydantic class hierarchy in
`base.py`: an `Instance` root (membership in $V$) with two disjoint subclasses,
`EntityInstance` and `BaseStatement`. `BaseStatement` is generic over its subject and
object types, so a predicate's domain and range are ordinary type annotations checked
by mypy and Pydantic. A worked domain (`Person`, `Organization`, `WorksFor`) lives in
`example.py`.

## Mini-tutorial

This walkthrough uses the domain defined in `example.py` — a small world of people,
organizations, and vehicles — to show how the pieces fit together.

### 1. Define your entity types

Entity types subclass `EntityInstance`. They are ordinary Pydantic models, so every
field gets type-checked at construction and the model is frozen (no mutation after
creation):

```python
from base import EntityInstance

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
```

Every instance carries a stable `id` field (inherited from `Instance`). You supply it
at construction; it is never parsed back to infer type — the class hierarchy owns that.

### 2. Define your predicate types

Predicate types subclass `BaseStatement[SubjectT, ObjectT]`. The type parameters
*are* the domain and range: mypy enforces them statically, Pydantic at runtime —
no hand-written validators needed.

```python
from base import BaseStatement, Inverse, Symmetric

# Single-type domain and range.
class WorksFor(BaseStatement[Person, Organization]):
    """dom = {Person}, ran = {Organization}."""

# Inverse trait: WorksFor(p, o) entails Employs(o, p).
class Employs(BaseStatement[Organization, Person], Inverse[WorksFor]):
    """dom = {Organization}, ran = {Person}."""

# Multi-member domain written as a | union.
class Owns(BaseStatement[Person | Organization, Vehicle]):
    """dom = {Person, Organization}, ran = {Vehicle}."""

# Symmetric trait: Knows(x, y) entails Knows(y, x).
class Knows(BaseStatement[Person, Person], Symmetric):
    """dom = ran = {Person}."""
```

### 3. Create entity instances

Instances are frozen Pydantic models — safe to share and use as dict keys:

```python
alice = Person(id="alice", name="Alice")
bob   = Person(id="bob",   name="Bob")
acme  = Organization(id="acme", name="Acme Corp", industry="widgets")
car   = Vehicle(id="car1", make="Toyota")
```

### 4. Create statements

A statement is also an `Instance` (it lives in $V$ alongside entities). Constructing
one validates the subject and object types immediately. Every statement carries a
`truth_status` field; the default is `"hypothetical"`:

```python
from base import Provenance

prov = Provenance(source="hr.csv", extraction_method="manual")

rel = WorksFor(
    id="alice-works_for-acme",
    subject=alice,
    object_=acme,
    truth_status="asserted_true",
    provenance=(prov,),   # one or more Provenance records, or None
)
```

A statement is *grounded* when `provenance` is a non-empty tuple (it has a traceable
source) and *ungrounded* when it is `None` (a hypothesis or derived fact without a
cited source). The two states are all-or-nothing — there is no partial provenance.

Trying to pass the wrong type for subject or object raises a Pydantic `ValidationError`
at construction time:

```python
WorksFor(id="bad", subject=acme, object_=alice, ...)  # ValidationError: acme is not a Person
```

### 5. Higher-order predication

Because a statement is a full member of $V$, one predicate can range over another.
`Believes` stores an entire statement as its object, preserving the concrete type:

```python
from base import AnyStatement

class Believes(BaseStatement[Person, AnyStatement]):
    """dom = {Person}, ran = any statement."""

belief = Believes(id="belief", subject=alice, object_=rel)
# belief.object_ is still a WorksFor, not a plain BaseStatement
assert isinstance(belief.object_, WorksFor)
```

`AnyStatement` is an `InstanceOf[BaseStatement]` validator exported from `base`. It
accepts any `BaseStatement` subclass and stores it without rebuilding it as the base
type, so the concrete predicate's traits, inverse declarations, and fields survive.

### 6. Build a Graph incrementally

`Graph` is an in-memory container and index over instances. You can build it
incrementally by adding entities and statements as they are created:

```python
from graph import Graph

g = Graph()
g.add(alice)
g.add(acme)
g.extend([bob, car])

g.add(rel)     # WorksFor statement
g.add(belief)  # Higher-order Believes statement

assert g.get("alice") is alice
assert g.edges_from("alice", pred_type=WorksFor) == [rel]
```

`Graph` also still supports bulk construction (`Graph([alice, acme, rel])`) when
you already have a full collection.

### 7. Serialize to runnable Python

`serialize.to_python` turns a list of instances into self-contained, topologically
ordered Python source. Instances referenced by others appear first; shared objects
are assigned to a variable once and reused by name — no duplication, no loss of
identity:

```python
from serialize import to_python

print(to_python([belief]))
```

The output is executable Python that reconstructs the exact graph when run. This makes
it straightforward to save a graph to a `.py` file and reload it with a plain
`exec`/`import`.

## Solve-and-ProbLog Pipeline

The Sherlock subproject is a worked reasoning demo for *A Scandal in Bohemia*.
The concrete question is the story's central mystery: where is Irene Adler's
incriminating photograph hidden?

The Sherlock mystery flow is intentionally split into two stages:

1. Deterministic solve (Horn clause via `datalog.Engine`)
2. Probabilistic ranking (ProbLog, optional)

The deterministic stage computes candidate places that are logically supported by
asserted facts. On the current dataset, deduction can narrow the candidate set but
cannot always select a unique winner. The probabilistic stage then ranks those
candidates using curated primitive random variables and evidence conditioning.

This keeps the core typed-graph + Datalog model transparent and truth-preserving,
while still supporting best-explanation ranking when the graph underdetermines a
single answer.

## Running the Mystery Modes

Run from the repository root.

Default import summary mode:

```bash
uv run python -m sherlock.demo
```

Deterministic mystery solve (Horn clause only):

```bash
SOLVE_MYSTERY=1 uv run python -m sherlock.demo
```

Probabilistic ranking mode (requires optional `problog` install):

```bash
SOLVE_MYSTERY_PROBLOG=1 uv run python -m sherlock.demo
```

Optional dataset controls:

```bash
SHERLOCK_DATASET_DIR=./sherlock/data SHERLOCK_STORY_PREFIX=bohemia uv run python -m sherlock.demo
```

Suggested verification for the probabilistic layer:

```bash
uv run pytest tests/test_sherlock_problog_adapter.py tests/test_sherlock_problog_scenario.py
```

---

## Domain and range

$\text{dom}(p)$ and $\text{ran}(p)$ are **sets** of types. A predicate binds them as
the type arguments of `BaseStatement`. When a set has one member, that's a single
type; when it has several, write them as a `|` union — the union *is* the set:

```python
# Singleton domain and range: dom = {Person}, ran = {Organization}
class WorksFor(BaseStatement[Person, Organization]): ...

# Multi-member sets via |: dom = {Person, Organization}, ran = {Vehicle}
class Owns(BaseStatement[Person | Organization, Vehicle]): ...
```

Use `|` anywhere a domain or range legitimately admits more than one type; the members
may overlap between domain and range, and either side may be widened this way
independently. mypy rejects a subject or object outside the declared set statically,
and Pydantic rejects it at construction — no hand-written validation. The subject side
must be entity types; the object side may also include a `BaseStatement` subclass,
which is how a predicate ranges over other statements (higher-order predication).

### Higher-order predication

When a predicate's object is itself a statement, its **concrete predicate type must be
preserved** — `Believes(alice, WorksFor(...))` should keep the object a `WorksFor`, so
you can still ask its traits, its inverse, or serialize it. For a range of "any
statement", declare it with `AnyStatement` (exported from `base`, an
`InstanceOf[BaseStatement]`):

```python
from base import AnyStatement, BaseStatement

class Believes(BaseStatement[Person, AnyStatement]):
    """dom = {Person}, ran = any statement (type preserved)."""
```

`AnyStatement` validates by `isinstance` and stores the object unchanged. A plain
`BaseStatement` / `BaseStatement[Any, Any]` range would instead rebuild the object as
the base class and lose its type. (Trade-off: an object given as a raw dict is
rejected — pass a real instance, or reconstruct one via the loader.)

## Traits

A **trait** is a declarative semantic property of a *predicate type* — it belongs to
the type, never to an individual statement (Hard Rule R1). In this package traits are
realized as **mixin classes** inherited alongside `BaseStatement`. The unparameterized
traits are plain marker classes; `Inverse` is generic, parameterized by the partner
predicate type.

> The marker traits and `Inverse` / `get_inverse` below are implemented in `base.py`;
> the snippets show how a predicate type opts in. `Rule` is realized differently —
> as Python objects in `rules.py` evaluated by `datalog.py`, not as a mixin — see the
> last subsection.

### Marker traits

```python
class Symmetric: ...
class Transitive: ...
class Functional: ...          # each subject has at most one object
class InverseFunctional: ...   # each object has at most one subject
```

A predicate opts in simply by inheriting the mixin alongside the typed base. Because
traits are ordinary base classes, they are introspectable at runtime with
`issubclass`:

```python
class Knows(BaseStatement[Person, Person], Symmetric):
    """Knows(x, y) implies Knows(y, x)."""

class ReportsTo(BaseStatement[Person, Person], Transitive, Functional):
    """ReportsTo is transitive, and each person reports to at most one other."""

issubclass(Knows, Symmetric)          # True
issubclass(ReportsTo, Transitive)     # True
issubclass(WorksFor, Symmetric)       # False
```

### Inverse(p') — the parameterized trait

`Inverse` is a generic mixin parameterized by the partner predicate type. Declaring
`ChildOf` as the inverse of `ParentOf` means `ParentOf(x, y)` entails `ChildOf(y, x)`:

```python
from typing import Generic, TypeVar

P = TypeVar("P", bound="BaseStatement")

class Inverse(Generic[P]): ...

class ParentOf(BaseStatement[Person, Person]):
    """ParentOf(x, y): x is a parent of y."""

class ChildOf(BaseStatement[Person, Person], Inverse[ParentOf]):
    """ChildOf(y, x): y is a child of x — the inverse of ParentOf."""
```

A helper resolves the declared partner from the type parameter:

```python
def get_inverse(stmt_type: type[BaseStatement]) -> type[BaseStatement] | None:
    """Return the partner predicate type if `stmt_type` declares Inverse, else None."""
    ...

get_inverse(ChildOf)   # -> ParentOf
get_inverse(WorksFor)  # -> None
```

### Rule(φ ⇒ ψ) — the escape hatch

`Symmetric`, `Transitive`, and `Inverse` are special cases of Datalog rules that the
type system can express directly:

| Trait          | Equivalent rule                                  |
|----------------|--------------------------------------------------|
| `Transitive`   | `p(x, y) ∧ p(y, z) ⇒ p(x, z)`                    |
| `Symmetric`    | `p(x, y) ⇒ p(y, x)`                              |
| `Inverse(p')`  | `p(x, y) ⇒ p'(y, x)`                             |

Anything that does not fit those named forms — cross-predicate rules, multi-hop
chains, rules with more than two body literals — is expressed with the full `Rule`
form. Unlike the marker traits, `Rule` has no type-level expression; it is built as
plain Python objects and evaluated at runtime:

```python
from rules import Rule, lit, variables
from datalog import Engine

x, y, z = variables("x y z")            # named, untyped logic variables

# Ancestor(x, z) :- Ancestor(x, y), Ancestor(y, z)
transitivity = Rule(lit(Ancestor, x, z), (lit(Ancestor, x, y), lit(Ancestor, y, z)))

eng = Engine()
eng.add_facts(known_ancestor_facts)     # only truth_status == asserted_true
eng.add_rule(transitivity)              # or eng.add_traits(Ancestor)
derived = eng.infer()                   # least fixed point; derived facts are grounded "inferred"
```

`lit(Pred, a, b)` is a rule *literal* (a predicate class with two arguments, each a
`Var` or a concrete `Instance`) — distinct from a `BaseStatement`, which is a member
of $V$. `Engine.add_traits` compiles the marker traits above into their equivalent
rules, so they and hand-written `Rule`s share one evaluator. Each derived head is
constructed through its predicate class, so domain/range are validated exactly as for
any statement. Rules are built directly in Python — there is deliberately no text
grammar or parser. See `formal-defns.md` §Trait vocabulary for the formal treatment.

### ProbLog when deduction is not enough

`Rule` is the escape hatch for deterministic logical inference. When deduction returns
multiple plausible candidates (as in the Sherlock mystery), the optional ProbLog layer
provides ranking by conditioning on evidence over a small set of primitive random
variables. In other words: keep Horn clauses for what must follow, then use ProbLog
for what is most likely among the remaining possibilities. See [docs/problog.md](docs/problog.md) for the design note and [sherlock/problog_adapter.py](sherlock/problog_adapter.py) for the adapter used by the demo.

Example (ProbLog syntax):

```prolog
% Deterministic Horn clause (always true when body is true)
physically_in(O, Place) :-
    possesses(P, O),
    associated_with(P, Place),
    happened_in(E, Place),
    involves(E, P).

% Probabilistic Horn clause (fires with probability 0.98)
0.98::photo_in_place(Place) :-
    reveal_coincidence_place(Place),
    alarm_reveal_moment,
    carry_event_feasible.
```

Read this as: if the body is satisfied, then `photo_in_place(Place)` is generated as
an uncertain conclusion with weight 0.98, rather than as a guaranteed fact.
