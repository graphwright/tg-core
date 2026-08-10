# Horn Clauses and Logical Inference

This document explains how the rule layer in [rules.py](rules.py) and the
deduction engine in [datalog.py](datalog.py) work together.

Short version:

- You define Horn-clause rules in Python.
- You feed asserted facts into the engine.
- The engine computes the least fixed point (all derivable facts).
- Derived facts are grounded with inferred provenance.

## What This Gives You

The rule engine gives you a compact way to derive new typed statements from
existing typed statements.

You can use it to:

- Materialize inverse relations (for example, `WorksFor` implies `Employs`).
- Materialize symmetric relations (for example, `Knows` implies reverse `Knows`).
- Materialize transitive closure fragments (for example, `Ancestor` chains).
- Keep all derived outputs type-safe by constructing through predicate classes.

It does not try to be a full Prolog or arbitrary logic runtime. It is a
focused, finite, bottom-up Datalog-style evaluator.

## Core Concepts

### Rules Are Python Objects, Not Text

In `rules.py`, a Horn clause is represented as:

- `Var`: a named logical variable.
- `Literal`: predicate class plus two arguments.
- `Rule`: head literal and body tuple of literals.

There is no rule parser. You build rules directly in Python.

Example shape:

```python
Rule(
	head=lit(Employs, o, p),
	body=(lit(WorksFor, p, o),),
)
```

This means:

`Employs(o, p) :- WorksFor(p, o)`

### Facts Are Typed Statements

Facts are ordinary `BaseStatement` instances from your domain model. The engine
only reasons over facts with `truth_status` equal to `asserted_true`.

Facts with other statuses are skipped by `add_facts` and counted in its return
value.

### Evaluation Is Bottom-Up to Fixed Point

In `datalog.py`, `Engine.infer` does iterative rounds:

1. Find all body matches against known facts.
2. Instantiate heads for each match.
3. Add newly derived facts.
4. Repeat until no new facts appear.

The result is the least fixed point for the provided rules and facts.

## Quick Tutorial

### 1. Define Variables and Rules

```python
from rules import Rule, lit, variables
from example import Employs, WorksFor

o, p = variables("o p")
inverse_rule = Rule(lit(Employs, o, p), (lit(WorksFor, p, o),))
```

### 2. Seed Facts

```python
from datalog import Engine
from example import WorksFor, alice, acme

eng = Engine()
eng.add_facts([
	WorksFor(id="wf1", subject=alice, object_=acme, truth_status="asserted_true")
])
```

### 3. Register Rules and Infer

```python
eng.add_rule(inverse_rule)
derived = eng.infer()
```

Now `derived` contains typed `Employs` statements.

### 4. Inspect Derived Provenance

Each derived fact is grounded with:

- `extraction_method = inferred`
- `source = repr(rule)`

So every derived edge points back to the rule that created it.

## Using Trait Compilation

If your predicate classes declare traits (Symmetric, Transitive, Inverse), you
can compile those traits into rules automatically.

```python
from datalog import Engine
from example import Knows, Employs

eng = Engine()
eng.add_facts([...])
eng.add_traits(Knows, Employs)
derived = eng.infer()
```

Trait expansion implemented by `Engine.add_traits`:

- Transitive: p(x, y) and p(y, z) implies p(x, z)
- Symmetric: p(x, y) implies p(y, x)
- Inverse: p(x, y) implies p_prime(y, x)

Functional and InverseFunctional are currently rejected here because they are
integrity constraints, not derivation rules.

## Hand-Written Horn Clause Examples

### Example 1: Inverse Relation (`WorksFor -> Employs`)

This is the smallest useful hand-written rule: if `p` works for `o`, then `o`
employs `p`.

```python
from datalog import Engine
from rules import Rule, lit, variables
from example import Employs, WorksFor, acme, alice

o, p = variables("o p")
inverse_rule = Rule(lit(Employs, o, p), (lit(WorksFor, p, o),))

eng = Engine()
eng.add_facts([
	WorksFor(id="wf1", subject=alice, object_=acme, truth_status="asserted_true")
])
eng.add_rule(inverse_rule)

derived = eng.infer()

# contains one Employs(acme, alice) fact
```

### Example 2: Two-Hop Join (`Knows` and `WorksFor`)

Here is a cross-predicate rule: if person `x` knows person `y`, and `y` works
for organization `o`, infer that `x` is associated with `o`.

```python
from base import BaseStatement, EntityInstance
from datalog import Engine
from rules import Rule, lit, variables
from example import Knows, Organization, Person, WorksFor, acme, alice, bob


class AssociatedOrg(BaseStatement[Person, Organization]):
	pass


x, y, o = variables("x y o")
rule = Rule(
	lit(AssociatedOrg, x, o),
	(
		lit(Knows, x, y),
		lit(WorksFor, y, o),
	),
)

eng = Engine()
eng.add_facts([
	Knows(id="k1", subject=alice, object_=bob, truth_status="asserted_true"),
	WorksFor(id="wf1", subject=bob, object_=acme, truth_status="asserted_true"),
])
eng.add_rule(rule)

derived = eng.infer()

# contains one AssociatedOrg(alice, acme) fact
```

This pattern is the key advantage of hand-written Horn clauses: you can express
joins across different predicates without introducing any text parser or custom
inference code.

## Full Example: Transitive Ancestor

```python
from base import BaseStatement, Transitive
from datalog import Engine
from example import Person


class Ancestor(BaseStatement[Person, Person], Transitive):
	pass


a = Person(id="a", name="A")
b = Person(id="b", name="B")
c = Person(id="c", name="C")

ab = Ancestor(id="ab", subject=a, object_=b, truth_status="asserted_true")
bc = Ancestor(id="bc", subject=b, object_=c, truth_status="asserted_true")

eng = Engine()
eng.add_facts([ab, bc])
eng.add_traits(Ancestor)

derived = eng.infer()

# one result is Ancestor(a, c)
```

## Validation and Safety Guarantees

### Rule Validation

When you call `Engine.add_rule`, `rules.validate_rule` enforces:

- No higher-order statement-valued literal arguments.
- Range restriction: every head variable must appear in the body.

Violations raise:

- `UnsupportedRuleError` for unsupported constructs.
- `UnsafeRuleError` for unbound head variables.

### Type Safety of Derived Facts

Derived heads are constructed through the predicate class, not by raw dict
assembly. That means normal Pydantic and model typing checks apply during
derivation.

If a rule implies an invalid domain or range assignment, you get a validation
error immediately.

## Deduplication and IDs

`Engine` uses a content-addressed key:

`predicate_module.predicate_qualname(subject_id,object_id)`

This is used to:

- avoid re-deriving the same fact repeatedly,
- merge corroborating provenance records,
- ensure fixed-point convergence in finite domains.

Seed facts keep their original id values. Derived facts use the content key.

## Provenance Behavior

The engine merges provenance for duplicate facts while preserving insertion
order and removing exact duplicates.

This applies to both:

- duplicate asserted facts, and
- repeated derivations of the same logical fact through different paths.

## Limitations and Non-Goals

Current boundaries of this rule system:

- Binary predicates only (subject and object positions).
- No higher-order rule literals.
- No negation or aggregation.
- No text-based rule DSL.
- Functional and InverseFunctional are not enforced as constraints.

## Common Workflow Pattern

1. Model your domain predicates as `BaseStatement` subclasses.
2. Create `asserted_true` fact instances.
3. Add facts with `Engine.add_facts`.
4. Add hand-written rules with `Engine.add_rule`, or trait-derived rules with
	`Engine.add_traits`, or both.
5. Call `Engine.infer` until it returns no new facts (`infer` already does this
   internally).
6. Persist or inspect derived facts, including provenance.

## Troubleshooting

If no facts derive:

- Confirm facts are asserted_true.
- Confirm your rule head and body predicates match intended direction.
- Confirm variable names are shared where joins should occur.

If `add_rule` fails:

- Check for head variables missing from body.
- Check for statement-valued literal arguments.

If `infer` raises `FixpointError`:

- Increase max_iterations temporarily for diagnosis.
- Check for non-idempotent fact identity assumptions in custom logic.

If `infer` raises a validation error:

- Your rule can produce domain/range-invalid heads.
- Fix predicate direction or constrain body patterns.
