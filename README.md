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

There are two kinds of reasoning supported here.

1. Deterministic solve (Horn clause via `datalog.Engine`)
2. Probabilistic ranking (ProbLog, optional)

The deterministic stage computes candidate places that are logically supported by
asserted facts. On the current dataset, deduction can narrow the candidate set but
cannot always select a unique winner. The probabilistic stage then ranks those
candidates using curated primitive random variables and evidence conditioning.

This keeps the core typed-graph + Datalog model transparent and truth-preserving,
while still supporting best-explanation ranking when the graph underdetermines a
single answer.

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
multiple plausible candidates, the optional ProbLog layer
provides ranking by conditioning on evidence over a small set of primitive random
variables. In other words: keep Horn clauses for what must follow, then use ProbLog
for what is most likely among the remaining possibilities. See [docs/problog.md](docs/problog.md) for the design note.

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

## Fundamentals

`base.py` is the whole formal model expressed as a Pydantic class hierarchy — the point is that mypy + Pydantic do the enforcing, so there's essentially no hand-written validation code. Four layers:

### 1. Vocabulary + provenance (`base.py:28-52`)

`TruthStatus` and `ExtractionMethod` are closed `Literal` unions, so values can't drift into `"inference"`/`"derived"` variants. `Provenance` is a frozen sub-model requiring both `source` and `extraction_method` — that's what makes R10's all-or-nothing rule structural: you either have a complete record or `None`.

### 2. The sorts: V and its partition (`base.py:55-73`)

```
Instance          # membership in V; frozen (R7); carries `id` (R9)
 ├── EntityInstance
 └── BaseStatement(Instance, Generic[SubjectT, ObjectT])
```

The two subclasses being disjoint siblings *is* the strict partition of `T` into entity and predicate types. `BaseStatement` inheriting `Instance` *is* `E ⊆ V` — nothing derives the edge set, it's just "the instances whose class is a `BaseStatement` subclass."

`dom(p)`/`ran(p)` are the type parameters: `class WorksFor(BaseStatement[Person, Organization])` and you're done — mypy checks statically, Pydantic at construction. Multi-type domain = a `Union` argument. Both `SubjectT` and `ObjectT` are bound to `Instance` rather than `EntityInstance`, which is what permits higher-order predication (R8): a statement can sit in either slot.

### 3. The two bits of real logic in the class

- `_ensure_provenance_tuple` (mode="before"): lets callers pass a bare `Provenance` or a `list`, normalizes to tuple. Note `base.py:109-110` — the `isinstance(data, dict)` guard is commented out, so a non-dict input to a `model_validate` call would blow up on `.get`.
- `_reject_empty_provenance` (mode="after"): `provenance=()` is an error. Empty tuple would be a third state between grounded and ungrounded, which R10 forbids.

`truth_status` defaults to `"hypothetical"` — presence of a statement is not assertion.

### 4. Traits (`base.py:173-233`)

Traits are properties of predicate *types* (R1), so they're mixin classes, not fields:

```python
class Knows(BaseStatement[Person, Person], Symmetric): ...
```

`Symmetric`, `Transitive`, `Functional`, `InverseFunctional` are bare markers under a common `Trait` base, so introspection is uniform `issubclass(x, Trait)`. `datalog.py` reads these and compiles them into rules.

`Inverse[PartnerT]` is the generic one. `get_inverse()` digs the type argument out of `__orig_bases__`, and resolves a `ForwardRef`/string partner against the declaring module's globals — needed for mutual inverses like `WorksFor`/`Employs` where one can't name the other yet. It's declared one-way: `get_inverse(ParentOf)` is `None` unless `ParentOf` also declares it.

`_validate_inverse_declaration` runs from `__init_subclass__`, so declaring `Inverse[P]` whose domain/range isn't P's swap is a `TypeError` at import time, not a silent bug. The `globals().get(...)` dance at `base.py:136` exists because subscripting `BaseStatement[Any, Any]` for the `PartnerT` bound makes Pydantic build generic submodels while the module is still loading — firing the hook before the validator function exists.

### Two supporting escape hatches

- `AnyStatement = InstanceOf[BaseStatement[Any, Any]]` — for "range is any statement." The comment at `base.py:141-147` explains why: a parametrized `BaseStatement[Any, Any]` slot would make Pydantic *rebuild* the value as the base class, destroying its concrete type (τ). `InstanceOf` validates by `isinstance` and keeps the object as-is. Cost: raw dicts get rejected, which is fine since `serialize.py` passes real instances.
- `_domain_range()` — reads type args from `__pydantic_generic_metadata__` rather than `get_args`, because a parametrized Pydantic generic is a real submodel class, not a typing alias.

## Service and Testing

A minimal FastAPI service (`app.py`) exposes the graph over HTTP for contract testing.
Install with the `[service]` optional dependency group:

```bash
uv sync --extra service
```

The service provides four endpoints over the example domain (alice, acme, car1):
- `GET /healthz` — health check
- `GET /entities/{id}` — retrieve an entity by ID
- `GET /entities/{id}/edges?direction=in|out` — get connected edges
- `GET /bfs?seed={id}&max_hops=N` — breadth-first traversal

Run it via docker-compose:

```bash
docker compose up -d --build
curl http://localhost:8000/api/v1/bfs?seed=alice
docker compose down
```

The service exists solely to validate the **keystone test** (`tests/test_keystone.py`),
marked `@pytest.mark.keystone`. This is the load-bearing contract test: if it passes,
the typed-graph implementation works end-to-end over the wire. If it fails, every other
test in the suite — which runs in-process — may be measuring a service that cannot
actually start or respond correctly.

```bash
# Start service first
docker compose up -d --build

# Run keystone test
uv run pytest -m keystone

# Clean up
docker compose down
```

The keystone test skips visibly (with instructions) when the service isn't listening,
rather than failing. See `tests/test_keystone.py` for the full contract.
