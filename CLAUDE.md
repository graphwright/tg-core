# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A **spec-first** project. It defines a typed-graph knowledge-representation model
and is growing a Python implementation of it. Any code written here must conform to
the formal model, not the other way around.

Layout:

- `base.py` — the reusable package: the class hierarchy (`Instance`,
  `EntityInstance`, `BaseStatement`), `Provenance`, the `TruthStatus` /
  `ExtractionMethod` literals, and the trait layer (`Symmetric`, `Transitive`,
  `Functional`, `InverseFunctional`, the generic `Inverse`, and the `get_inverse`
  resolver). Types are Python classes, not data (the class-per-type model).
- `example.py` — a worked domain built on `base` (`Person`, `Organization`,
  `Vehicle`; predicates `WorksFor`, `Employs`, `Owns`, `Knows`, `Believes`).
- `graph.py` — `Graph`, an in-memory container and index over instances. Supports
  incremental construction (`add`, `extend`), lookup by ID, edge traversal
  (`incoming_edges`, `outgoing_edges`), and BFS walks.
- `rules.py` — Python-native Horn-clause rules (`Var` / `variables`, `Literal` /
  `lit`, `Rule`) plus the rule/deduction exception hierarchy (`RuleError` and
  subclasses). Rules are built in Python, not parsed from text.
- `datalog.py` — `Engine`, a naive bottom-up Datalog deduction engine (fixed-point
  over the asserted graph; `add_traits` compiles `Transitive`/`Symmetric`/`Inverse`
  into rules; derived facts are grounded `inferred`).
- `serialize.py` — `to_python` / `from_python`: serialize a graph to runnable
  Python source and back. Deserialization is `exec` (no parser); output is a flat,
  topologically ordered program with one variable per instance, referencing
  instance-valued fields by name to preserve sharing and higher-order structure.
- `logconfig.py` — stdlib logging setup (`configure`, `get_logger`, `FORMAT`). Purely
  operational, outside the formal model: the schema/instance modules must not import
  it, so they stay import-side-effect free. Level from `configure(level=...)`, else
  `LOG_LEVEL`, else INFO.
- `app.py` — minimal FastAPI service exposing graph endpoints (`/healthz`,
  `/entities/{id}`, `/entities/{id}/edges`, `/bfs`) over the example domain.
  Requires `[service]` optional dependencies. Used only for keystone contract testing.
- `tests/test_base.py`, `tests/test_example.py`, `tests/test_datalog.py`,
  `tests/test_serialize.py`, `tests/test_graph.py` — pytest cases (happy path,
  wrong-type rejection, `E ⊆ V` membership, ungrounded-hypothetical default, trait
  introspection, inverse resolution, deduction / fixed point, Python-source round trip,
  graph operations).
- `tests/test_keystone.py` — the load-bearing contract test: validates the service
  works end-to-end over HTTP (marked `@pytest.mark.keystone`). Requires
  `docker compose -f docker-compose.service.yml up -d --build` first.
- `docs/formal-defns.md`, `README.md` — the design documents (see below).

**Read these before writing any code, prose, or schema:**

- `formal-defns.md` — the **authoritative** formal model. Defines the typed graph as
  the 4-tuple $(T, \Phi, V, \tau)$, the vocabulary, the ten Hard Rules (R1–R10), the
  Python enforcement pattern, and the Non-Goals. When in doubt, this file wins.
- `README.md` — the informal, Python-developer-facing framing of the same model,
  including a Traits section with sample code. The marker traits and `Inverse` are
  implemented in `base.py`; `Rule` (the Datalog escape hatch) is realized in Python
  by `rules.py` + `datalog.py` (Horn clauses built as `Rule`/`Literal` objects with
  `variables("x y z")`, evaluated to a least fixed point). There is deliberately no
  text-grammar / parser for rules.

## Toolchain

Managed by **uv** (Python 3.12, pinned in `.python-version`). Prefer `uv run …` over
bare `python`/`pytest`/`mypy`.

```bash
uv sync                    # install/refresh the venv from pyproject + lockfile
uv run pytest              # run the test suite (skips keystone by default)
uv run pytest path/to/test_file.py::test_name   # run a single test
uv run mypy .              # strict type check (see rules below — this is not optional)
uv add <pkg>               # add a runtime dependency
uv add --dev <pkg>         # add a dev/tooling dependency
```

Runtime deps: `pydantic` (v2), `httpx2`. Dev deps: `mypy`, `pytest`. `typing` is stdlib
on 3.12 — do not add the PyPI `typing` backport.

Optional dependency groups:
- `[reasoning]` — `datalog`, `problog` (not currently used)
- `[service]` — `fastapi`, `uvicorn` (required for `app.py` and keystone test)

## Testing

The test suite has two parts:

1. **Unit/integration tests** (default) — run in-process against the core modules
   (`base`, `graph`, `datalog`, `serialize`). These are fast and run on every commit.
   ```bash
   uv run pytest   # runs all tests except keystone
   ```

2. **Keystone test** — the load-bearing contract test that validates the service works
   end-to-end over HTTP. Marked with `@pytest.mark.keystone`. This test requires the
   service to be running first:
   ```bash
   docker compose up -d --build
   uv run pytest -m keystone
   docker compose down
   ```

The keystone test is deliberately NOT excluded by default (no `addopts = "-m 'not keystone'"`
in `pyproject.toml`) because silent deselection would recreate the exact failure the test
exists to catch. Instead, it skips visibly when the service isn't listening.

## The model, in brief

The whole point is a strict **schema vs. instance** split, realized in the Python
class hierarchy so that mypy + Pydantic enforce the formalism with no custom
validation code:

- **Schema layer** (fixed at design time): `T` = types, partitioned strictly into
  entity types and predicate types; `Φ` = per-type Pydantic field schema; plus
  `dom(p)`, `ran(p)`, and traits `Tr(p)` per predicate.
- **Instance layer** (populated at ingestion/reasoning time): `V` = all instances,
  `τ` = type assignment. The edge set `E = {v ∈ V : τ(v) ∈ T_pred}` is **derived**,
  and `E ⊆ V` — a predicate instance is a full member of `V` and can itself be the
  subject/object of another predicate (higher-order predication, no reification).

Class hierarchy that any implementation must mirror:

```
Instance                 # root; carries `id`; realizes membership in V; frozen
 ├── EntityInstance      # entity types (Person, Location, …)
 └── BaseStatement       # predicate types; carries subject / object_ / truth_status
                         #   trait mixins inherited alongside (Symmetric, Transitive, …)
```

`EntityInstance` and `BaseStatement` are **disjoint siblings** — that realizes the
strict partition of `T`. `BaseStatement` is generic:
`BaseStatement(Instance, Generic[SubjectT, ObjectT])` with `subject: SubjectT`,
`object_: ObjectT` (trailing underscore avoids shadowing the builtin). A concrete
predicate binds the parameters — `class WorksFor(BaseStatement[Person, Organization])`
— so `dom(p)`/`ran(p)` are just the type arguments, enforced by mypy statically and
Pydantic at construction. `SubjectT` is bound to `EntityInstance`; `ObjectT` is bound
to `Instance`, so a statement's object may itself be a statement (higher-order
predication). A multi-type domain/range is a `Union` argument
(`BaseStatement[Person | Organization, Vehicle]`) — no custom validation code either
way.

## Two independent projections of the edge set

Both are subsets of `E` and are **orthogonal and composable** — a query may require
one, the other, both, or neither:

- **Asserted graph** — `truth_status == asserted_true`. Presence of a statement is
  *not* assertion; `truth_status` (`asserted_true` / `asserted_false` / `hypothetical`
  / `disputed` / `retracted`) carries it. Closed-world.
- **Grounded subgraph** — `provenance is not None`. Statements backed by a source or a
  derivation. Its complement is ungrounded, hypothetical-origin statements.

Require **both** when only source-backed facts are acceptable; admit ungrounded
statements when exploring what-ifs.

## Hard rules that govern all code here (from `formal-defns.md`)

Violating these is a design error, not a style nit. The full text is in
`formal-defns.md` §Hard Rules; the ones with direct coding impact:

- **R6** — Domain/range are enforced by the type system: concrete class annotations on
  `subject`/`object_`, `Union` (`Person | Organization`) when multiple types are
  allowed. No hand-written domain/range validators.
- **R7** — Instance models are **frozen**: `model_config = ConfigDict(frozen=True)`.
- **R1/R2** — Traits belong to predicate *types* (mixin classes); metadata
  (provenance, confidence, timestamps) belongs to *instances*. Never swap these.
- **R9** — Every instance has a stable `id` assigned at construction; **never parse an
  id string to recover or dispatch on type** — `τ`/the class hierarchy owns type.
  Human-readable display is `__str__`'s job, one-way, never parsed back.
- **R10** — Provenance is **optional per instance but all-or-nothing in form**. Every
  predicate type declares one field `provenance: tuple[Provenance, ...] | None`, where
  `Provenance` is a frozen sub-model requiring `source` and `extraction_method`. A
  statement is *grounded* (one or more complete `Provenance` records) or *ungrounded*
  (`None`) — never partial. Do not scatter optional `source`/`extraction_method`
  fields onto the statement; do not assume every statement is grounded — restrict to
  the grounded subgraph when you need source-backed facts. Rule-derived instances are
  grounded with `extraction_method = inferred`.
- **R8** — Higher-order predication is a schema-level range declaration
  (`object_: BaseStatement`), not a runtime promotion, and must not be used to attach
  metadata (that is R2's job).

## Non-Goals (do not drift toward these)

Not RDF/OWL, not Neo4j's schemaless property graph, not an ER diagram, not a general
ontology language, not a stringly-typed system. See `formal-defns.md` §Non-Goals.

## Worked domain

`example.py` currently uses a minimal `Person` / `Organization` / `WorksFor` example.
