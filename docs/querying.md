# BFS-QL: A Graph Query Language for LLMs

## Overview

The BFS query ([breadth-first search](https://en.wikipedia.org/wiki/Breadth-first_search)) provides a single, general-purpose mechanism for retrieving subgraphs from the
knowledge graph. It is designed to be constructed easily by an LLM while minimizing unnecessary
context window consumption in the response.

The design separates two orthogonal concerns:

- **Topology**: BFS from one or more seed nodes up to a specified hop depth defines which nodes
  and edges are included in the subgraph. Filtering has no effect on this.
- **Presentation**: Node and edge filters determine which items in that subgraph receive full
  metadata vs. a minimal stub. This is purely a serialization decision applied after the
  subgraph is computed.

Stub items carry only enough information to understand the graph's topology without consuming
context on irrelevant details. The LLM sees the full shape of the neighborhood while receiving
rich data only where it matters.

Several refinements extend this design for graphs with richer semantics:

- **Traversal filters** (`truth_status`, `as_of`) are a third concern, distinct from both
  topology and presentation: each constrains which edges BFS is *allowed to follow*, and
  therefore does affect the resulting subgraph — unlike presentation filters, which never do.
  See [Truth Status](#truth-status-a-traversal-filter) and
  [Temporal Snapshots](#temporal-snapshots-the-as_of-filter).
- **Reified statements** model relationships as first-class nodes rather than plain edges, so a
  relationship can carry its own provenance and can itself be the subject or object of other
  statements — including query-time expansion of `Symmetric` and `Inverse` relationships that
  were never separately asserted. See [Reified Statements](#reified-statements-edges-as-nodes)
  and [Trait-Aware Query Expansion](#trait-aware-query-expansion).
- **Not every question is a neighborhood.** "Find every statement of this kind, wherever it is
  in the graph" has no natural seed node. See
  [Scan Query](#scan-query-search-without-a-seed).

### Query primitives at a glance

| Primitive | Shape | Use when |
|---|---|---|
| `bfs_query()` | seeds + hops → layered subgraph | "What's near X, considering several relationship types?" |
| `transitive_closure_query()` | start + one predicate → flat reachable set | "Everything transitively related to X via *this one* relationship, however many hops that takes." |
| `scan_query()` | type/status/time filters → flat match list, no seed | "Find every node or statement of this kind, wherever it is in the graph." |

The rest of this document covers `bfs_query()` first, since it's the workhorse and the other
two primitives borrow its filter vocabulary, then covers the narrower primitives in their own
sections.

---

## Query Format

```json
{
  "seeds": ["<entity_id>", ...],
  "max_hops": <int>,
  "truth_status": ["<status>", ...],
  "as_of": <cutoff>,
  "expand_traits": ["<trait>", ...],
  "node_filter": {
    "entity_types": ["<type>", ...]
  },
  "edge_filter": {
    "predicates": ["<predicate>", ...]
  }
}
```

### Fields

| Field | Required | Description |
|---|---|---|
| `seeds` | Yes | Array of one or more canonical entity IDs to use as BFS starting points. All seeds are expanded simultaneously; the result is the union of their neighborhoods. |
| `max_hops` | Yes | Maximum graph distance from any seed node. Values of 1–3 are typical; larger values may return very large subgraphs. |
| `truth_status` | No | **Traversal filter.** List of epistemic statuses (e.g. `asserted_true`, `asserted_false`, `hypothetical`, `disputed`, `retracted`) an edge must have to be followed at all. Unlike the presentation filters below, this constrains topology — edges outside this set are never traversed, so their far endpoints may be absent from the subgraph entirely. Defaults to `["asserted_true"]` when omitted. See [Truth Status](#truth-status-a-traversal-filter). |
| `as_of` | No | **Traversal filter.** A cutoff on when a statement entered the record (a sentence/paragraph index, timestamp, or document version — domain-specific). Only statements asserted at or before the cutoff are traversable. Defaults to no cutoff (the full graph) when omitted. See [Temporal Snapshots](#temporal-snapshots-the-as_of-filter). |
| `expand_traits` | No | List of trait names (`Symmetric`, `Inverse`) to honor at query time even where no matching statement was separately asserted. Derived edges/nodes are marked `derived_via` in the response. Defaults to no expansion. See [Trait-Aware Query Expansion](#trait-aware-query-expansion). |
| `node_filter` | No | Controls which nodes receive full metadata. Nodes not matching the filter appear as stubs. Omit to receive full data on all nodes. |
| `node_filter.entity_types` | No | List of entity type names. A node matches if its type is in this list. |
| `edge_filter` | No | Controls which edges receive full metadata including provenance. Edges not matching appear as stubs. Omit to receive full data on all edges. |
| `edge_filter.predicates` | No | List of predicate names. An edge matches if its predicate is in this list. |

### Notes

- If `node_filter` is omitted entirely, all nodes in the subgraph receive full data.
- If `edge_filter` is omitted entirely, all edges receive full data including provenance.
- If `truth_status` is omitted, BFS follows only `asserted_true` edges — hypothetical, disputed,
  retracted, and false statements are excluded from traversal by default, not merely stubbed.
  Pass an explicit list (e.g. `["asserted_true", "disputed"]`) to widen traversal.
- If `as_of` is omitted, BFS traverses the complete graph regardless of when each statement was
  asserted. `as_of` and `truth_status` are independent and compose freely.
- If `expand_traits` is omitted, BFS only follows edges that were actually asserted — no
  trait-derived edges are surfaced.
- Omitting both presentation filters is appropriate for small subgraphs or debugging, but will
  produce large responses on dense neighborhoods.
- Multiple seeds are useful when you want to explore the shared neighborhood of several
  entities simultaneously — for example, finding publications co-authored by two researchers,
  or finding diseases connected to a set of genes.
- If you do not yet have a canonical entity ID, call `search_entities()` first to resolve a
  name to an ID. Some ID forms (e.g. a full URL that names an entity) may be normalized to a
  canonical ID automatically by the query layer — see [ID Canonicalization](#id-canonicalization).

---

## Response Format

```json
{
  "seeds": ["<entity_id>", ...],
  "max_hops": 2,
  "node_count": <int>,
  "edge_count": <int>,
  "nodes": [
    {
      "id": "<entity_id>",
      "entity_type": "<type>",
      "<additional fields>": "..."
    }
  ],
  "edges": [
    {
      "subject": "<entity_id>",
      "predicate": "<predicate>",
      "object": "<entity_id>",
      "<additional fields>": "..."
    }
  ]
}
```

### Full Node

A node that matches the `node_filter` (or when no filter is specified) includes all available
metadata:

```json
{
  "id": "PUB:PMC2386281",
  "entity_type": "Publication",
  "title": "The Diagnosis of Cushing's Syndrome",
  "canonical_id": "PMID:18493314",
  "year": 2008,
  "journal": "Reviews in Endocrine and Metabolic Disorders",
  "authors": ["Stewart PM"],
  "abstract_snippet": "..."
}
```

### Stub Node

A node that does not match the `node_filter` appears as a stub with only identity information:

```json
{
  "id": "PERSON:67890",
  "entity_type": "Person"
}
```

### Full Edge

An edge that matches the `edge_filter` (or when no filter is specified) includes all provenance
and metadata:

```json
{
  "subject": "PERSON:12345",
  "predicate": "AUTHORED",
  "object": "PUB:PMC2386281",
  "confidence": 0.97,
  "provenance": [
    {
      "source_doc": "PMC2386281",
      "section": "metadata",
      "method": "structured_extraction",
      "evidence_type": "primary_authorship"
    }
  ]
}
```

### Stub Edge

An edge that does not match the `edge_filter` appears with topology only:

```json
{
  "subject": "PERSON:12345",
  "predicate": "COLLEAGUE_OF",
  "object": "PERSON:67890"
}
```

---

## Reified Statements (Edges as Nodes)

Some typed graphs model every relationship as a first-class **statement** node — a subject →
predicate → object assertion with its own ID — rather than as a plain edge bolted onto two
nodes. This pattern ("reification") matters whenever a relationship itself needs to carry
provenance, or needs to be referenced by other statements.

```json
{
  "id": "stmt:wiki:Sherlock_Holmes:Possesses:obj:cigar_case",
  "node_kind": "statement",
  "predicate": "Possesses",
  "subject_id": "wiki:Sherlock_Holmes",
  "object_id": "obj:cigar_case",
  "truth_status": "asserted_true",
  "story_id": "sib",
  "paragraph_index": 4,
  "sentence_ids": [12, 13],
  "asserting_narrator_id": "wiki:Dr_Watson",
  "extraction_method": "structured_extraction",
  "extraction_confidence": 0.94
}
```

A statement node's `subject_id` and `object_id` can themselves point at other statement nodes,
not just entities — enabling meta-statements such as "Watson doubts that [Holmes possesses the
cigar case]," where the doubted claim is the object of a second statement.

Consequences for the query language above:

- Statement nodes flow through the same `nodes` array as entity nodes; `node_filter.entity_types`
  can include a value like `"Statement"` to request full statement metadata (predicate,
  provenance, truth status) or leave statements stubbed to `{id, entity_type}` when only
  topology is needed.
- Because a statement is a node, it also occupies a BFS layer of its own — a hop that crosses a
  relationship lands on the statement first, then on the far entity one hop later. Graphs that
  reify should document this off-by-one so LLMs aren't surprised by `max_hops` covering fewer
  entities than expected.
- A dedicated `edges` array becomes a convenience projection over statement nodes rather than
  the only place relationship data lives; graphs that fully reify may omit it and let
  `bfs_query()` return only `nodes`.
- Provenance fields are domain-specific — a narrative source (`story_id`, `paragraph_index`,
  `sentence_ids`, `asserting_narrator_id`) looks different from a document source
  (`source_doc`, `section`, `evidence_type`), but both are "full edge/statement" data gated by
  the same presentation filter.
- Full statement data always includes `extraction_method` (e.g. `structured_extraction`,
  `manual`, `inferred`) alongside `truth_status`. This makes provenance auditable down to
  whether a fact was read directly from a source or derived after the fact — see
  [Trait-Aware Query Expansion](#trait-aware-query-expansion) for the query-time analogue and
  its boundary.
- A statement's shape isn't fixed at `{subject, predicate, object}`. Domain schemas can attach
  further typed relata — e.g. a knowledge-statement whose `object_id` is itself another
  statement (nesting, as above) plus a separate field anchoring *when* the knowledge became
  true. Full statement data includes whatever extra typed fields the schema defines; the
  presentation filter gates the whole statement, not individual fields within it.

---

## Trait-Aware Query Expansion

Some predicates carry structural traits — `Transitive`, `Symmetric`, `Inverse(p')` — that are
themselves restricted Horn-clause shapes:

| Trait | Rule shape |
|---|---|
| `Transitive` | `p(x, y) ∧ p(y, z) ⇒ p(x, z)` |
| `Symmetric` | `p(x, y) ⇒ p(y, x)` |
| `Inverse(p')` | `p(x, y) ⇒ p'(y, x)` |

Each shape is a single predicate, no function symbols, no negation, and no existential
variable in the head — the same restrictions that make Datalog decidable. Because they're this
narrow, all three can be evaluated **at query time**, without ever writing a new statement into
the graph. `transitive_closure_query()` already does exactly this for `Transitive`: it answers
a reachability question by walking the asserted subgraph on the fly, the same way it would if
every transitive fact had been separately materialized, but without asserting anything.

`expand_traits` only needs to name the other two shapes, `Symmetric` and `Inverse` —
`Transitive` already has its own dedicated primitive, because a full transitive closure is
unbounded in depth and doesn't fit inside a fixed `max_hops` budget the way a `Symmetric` or
`Inverse` mirror does: the mirrored edge sits at the *same* hop as the edge it mirrors, adding
no depth at all. `bfs_query()` exposes that same-hop mirroring with an optional `expand_traits`
list:

```json
{
  "seeds": ["wiki:Nonconformist_Clergyman"],
  "max_hops": 1,
  "expand_traits": ["Inverse"]
}
```

If `DisguisedAs(Holmes, Nonconformist_Clergyman)` is asserted and `HasTrueIdentity` is declared
its `Inverse`, this query surfaces `HasTrueIdentity(Nonconformist_Clergyman, Holmes)` as if it
were a normal edge from the seed — computed on the fly, never written back to the graph. The
same applies to `Symmetric` predicates in either direction.

A trait-expanded edge is marked distinctly in the response, e.g.:

```json
{
  "subject": "wiki:Nonconformist_Clergyman",
  "predicate": "HasTrueIdentity",
  "object": "wiki:Sherlock_Holmes",
  "derived_via": "Inverse(DisguisedAs)"
}
```

so the LLM can tell "the graph directly asserts this" apart from "this follows structurally
from something the graph asserts" — the same auditability `extraction_method="inferred"`
provides for a *materialized* derived fact, applied here to a fact that was never materialized
at all.

**Where this stops:** the general `Rule(phi => psi)` escape hatch — arbitrary cross-predicate
Horn clauses, or rules with a non-graph test in the body (a string match against a description,
say) — is *not* eligible for query-time expansion. It isn't guaranteed decidable or cheap, and
it may not even be a strict Datalog rule. Firing one requires an actual inference engine, which
writes a new, honestly-provenanced statement (`extraction_method="inferred"`) into the graph.
Once that happens, the derived statement is just an ordinary statement to the query language —
reachable through the normal traversal and presentation filters like anything else. The query
layer only ever performs cheap, structural, read-only inference — ordinary BFS traversal,
`transitive_closure_query()`'s fixed-point walk, and `expand_traits`' same-hop trait mirroring —
never an arbitrary rule on the caller's behalf.

---

## Truth Status: A Traversal Filter

Statements can carry an epistemic status distinct from whether they're true in the fiction of
the graph's source material: `asserted_true`, `asserted_false`, `hypothetical`, `disputed`,
`retracted`. This status is what a narrator or source claims, which is not the same thing as
established fact — a story can contain a statement that is later retracted, a hypothesis a
detective raises and drops, or a claim two characters dispute.

`truth_status` is a **traversal filter**, not a presentation filter: it decides which edges BFS
walks across, not merely how much detail a matched edge reports. This is why it lives in the
top-level query alongside `seeds` and `max_hops` rather than inside `edge_filter`. The default
(`["asserted_true"]`) exists so an LLM exploring the graph doesn't silently absorb a
hypothetical or retracted claim as settled fact — widening the filter is an explicit choice.

Use a wider `truth_status` list when the task is specifically about uncertainty or
disagreement — e.g. "what does Watson doubt?" or "what hypotheses did Holmes raise and later
abandon?" — where `disputed` or `hypothetical` statements are exactly what's being asked for.

`truth_status` is about reliability, not timing — see
[Temporal Snapshots](#temporal-snapshots-the-as_of-filter) for the complementary question of
*when* a statement entered the record. The two compose freely: `truth_status: ["asserted_true"]`
combined with `as_of: 485` asks "what was confidently known before sentence 485"; dropping
`as_of` asks the same reliability question against the complete graph instead.

---

## Temporal Snapshots: The `as_of` Filter

Facts don't all enter a knowledge graph at once, and sometimes the question isn't "what is
true" but "what was known at a given point" — reconstructing the evidence available before a
reveal, auditing what could have been concluded before a later correction, or replaying how
understanding of a situation grew over the course of a narrative or a data feed.

`as_of` is a **traversal filter** like `truth_status`, applied independently: a statement is
only traversable if its provenance places it at or before the cutoff. What counts as "before"
is domain-specific — a sentence or paragraph index in an extracted narrative, a document
version, a wall-clock timestamp — but the shape of the filter is the same regardless: an
ordering over statements, plus a cutoff value.

```json
{
  "seeds": ["wiki:Irene_Adler"],
  "max_hops": 1,
  "as_of": 485
}
```

Result: only statements whose provenance places them at or before position 485 are traversed.
A `Possesses(Irene, photograph)` statement extracted from a later sentence is invisible to this
query — not stubbed, not filtered from presentation, simply not reachable — even though it's
present, `asserted_true`, and undisputed in the full graph.

Omitting `as_of` queries the complete graph, with no temporal restriction. Unlike
`truth_status`, there's no conservative default to apply here: there's no version of "the
current state" that's inherently safer than "everything ever asserted," so `as_of` defaults to
off rather than to some implicit cutoff.

---

## Transitive Closure Query

BFS is the right tool when you want a bounded, multi-predicate neighborhood. It's the wrong
tool for a single-predicate chain where you want the *entire* reachable set regardless of
depth — e.g. every location transitively `part_of` a region, or every document transitively
`derived_from` a source. For that, use a dedicated transitive-closure primitive instead of
picking an arbitrarily large `max_hops`.

```json
{
  "start": "<entity_id>",
  "predicate": "<predicate>"
}
```

```json
{
  "start": "wiki:Baker_Street",
  "predicate": "PartOf"
}
```

Result: a flat, unlayered list of every entity ID reachable by following only `PartOf` edges
to a fixed point — no hop limit, no other predicates mixed in, no node or edge filters. It
answers an existence/membership question ("is X transitively part of Y's closure?") cheaply,
returning identity-only IDs rather than a full subgraph. Reach for `bfs_query()` instead as
soon as you need more than one predicate, a bounded radius, or full metadata on what you find.

---

## Scan Query: Search Without a Seed

`bfs_query()` and `transitive_closure_query()` both start from one or more seed entities and
describe a neighborhood. Some questions have no natural seed at all: "does the graph contain
any disputed statements?", "list every entity of type Location," "show me everything asserted
before a given cutoff." For these, use `scan_query()`.

```json
{
  "node_types": ["<type>", ...],
  "edge_predicates": ["<predicate>", ...],
  "truth_status": ["<status>", ...],
  "as_of": <cutoff>
}
```

```json
{
  "edge_predicates": ["DisguisedAs"],
  "truth_status": ["asserted_true"]
}
```

Result: every statement in the graph matching predicate `DisguisedAs` and status
`asserted_true`, returned in full — wherever its subject and object sit in the graph, with no
notion of hop distance from anything. A query with `node_types: ["Location"]` instead returns
every Location entity, full stop.

`scan_query()` shares its traversal-filter vocabulary (`truth_status`, `as_of`) with
`bfs_query()`, but has no `max_hops` and no presentation filters — there's no neighborhood to
stub, since every match is exactly what was asked for and is returned in full. Reach for it
when the question is about the graph's *contents* rather than about a *neighborhood*.

---

## Scandal in Bohemia: Query Right Before the Reveal

The interesting Sherlock question is often:

"Given what is known immediately before Holmes announces the answer, where is
Irene Adler's photograph?"

This is a two-step pattern:

1. Use query primitives (`bfs_query()` / `scan_query()`) to gather the relevant
  local facts and timeline clues.
2. Apply rule-layer inference (a hand-written Horn clause) to produce the final
  location statement.

Why split it this way:

- Query tools are great for neighborhood and filtering.
- The final leap is a cross-predicate join that is best represented as an
  explicit rule.

In this repository, that end-to-end flow is implemented in `sherlock/demo.py`
under `SOLVE_MYSTERY=1`.

Typical fact pattern to retrieve before applying the rule:

- Possession facts for Irene and the photograph.
- Event participation around the staged fire-alarm sequence.
- Time anchoring for those events (`OccurredAt` moments).
- Location context for the key room when available.

This keeps querying focused on collecting evidence and keeps inference explicit,
auditable, and reproducible.

---

## ID Canonicalization

Entities are sometimes named more than one way in source data — a full URL and a short slug
ID, for instance. The query layer should canonicalize known alternate forms (e.g.
`https://example.org/wiki/Sherlock_Holmes` → `wiki:Sherlock_Holmes`) transparently on every ID
accepted as input (`seeds`, `start`, entity IDs embedded in filters) and every ID returned in a
response, so the LLM never has to normalize IDs itself or treat two spellings of the same ID as
different nodes. This does not replace `search_entities()` — canonicalization only maps one
known ID form to another; it cannot resolve a bare name to an ID.

---

## LLM Prompt

The following section can be included in a system prompt or tool description to instruct an
LLM how to construct BFS queries.

---

### Using `bfs_query()`

To explore the knowledge graph, call `bfs_query()` with a JSON body. The query performs a
breadth-first search from one or more seed nodes and returns the resulting subgraph.

Nodes and edges in the subgraph are either **full** (all metadata and provenance included) or
**stub** (identity only), depending on the `node_filter`/`edge_filter` you specify. Those two
filters affect only what data is returned, not which nodes and edges are included in the
subgraph. `truth_status` is different: it decides which edges BFS is willing to traverse at
all, and so it does change which nodes end up in the subgraph. See
[Truth Status](#truth-status-a-traversal-filter) if you're unsure which one you need.

**If you do not yet have a canonical entity ID, call `search_entities()` first.**

**For a single-predicate chain with no depth limit** (e.g. "everything transitively part of
X"), use `transitive_closure_query()` instead — see
[Transitive Closure Query](#transitive-closure-query).

**For a whole-graph search with no seed at all** (e.g. "find every disputed statement," "list
every entity of type Location"), use `scan_query()` instead — see
[Scan Query](#scan-query-search-without-a-seed).

#### Query structure

```json
{
  "seeds": ["<id>", ...],       // one or more starting entity IDs
  "max_hops": <int>,            // graph distance from seeds (1-3 recommended)
  "truth_status": [...],        // optional: which edges may be traversed at all
                                 // e.g. ["asserted_true", "disputed"]; defaults to ["asserted_true"]
  "as_of": <cutoff>,            // optional: only traverse statements asserted at/before this point
                                 // e.g. a sentence index; defaults to no cutoff (the full graph)
  "expand_traits": [...],       // optional: surface Symmetric/Inverse edges not separately
                                 // asserted, computed at query time; e.g. ["Inverse"]
  "node_filter": {              // optional: which nodes get full data
    "entity_types": [...]       // e.g. ["Publication", "Disease", "Drug"]
  },
  "edge_filter": {              // optional: which edges get full data + provenance
    "predicates": [...]         // e.g. ["AUTHORED", "TREATS", "INHIBITS"]
  }
}
```

Stub nodes contain only `{id, entity_type}`.
Stub edges contain only `{subject, predicate, object}`.
Omitting `node_filter` or `edge_filter` returns full data for all nodes or edges respectively.
Omitting `truth_status` restricts traversal to `asserted_true` edges only.
Omitting `as_of` traverses the full graph regardless of when statements were asserted.
Omitting `expand_traits` surfaces only edges that were actually asserted.

---

#### Example 1: Find an author's publications with provenance

You know Dr. Stewart's entity ID and want to retrieve her publications along with the evidence
that links her to each one. You don't need full metadata on other entities in the neighborhood.

```json
{
  "seeds": ["PERSON:12345"],
  "max_hops": 1,
  "node_filter": {
    "entity_types": ["Publication"]
  },
  "edge_filter": {
    "predicates": ["AUTHORED"]
  }
}
```

Result: Full data on Publication nodes, full provenance on AUTHORED edges. Any other nodes
or edges at hop 1 (e.g. institutional affiliations) appear as stubs.

---

#### Example 2: Explore a disease neighborhood, focusing on drugs

You want to understand what drugs are connected to Cushing's syndrome within two hops, without
being overwhelmed by the full metadata of every gene, symptom, and pathway in the neighborhood.

```json
{
  "seeds": ["UMLS:C0085084"],
  "max_hops": 2,
  "node_filter": {
    "entity_types": ["Drug"]
  }
}
```

Result: Full data on Drug nodes. All other node types (Disease, Gene, Symptom, etc.) appear
as stubs. All edges appear as stubs since no `edge_filter` targets specific predicates — you
can see the topology of the neighborhood without consuming context on provenance you haven't
asked for.

---

#### Example 3: Find shared connections between two entities

You want to explore what two researchers have in common — shared publications, shared diseases
they've written about, or shared collaborators — within two hops of either of them.

```json
{
  "seeds": ["PERSON:12345", "PERSON:67890"],
  "max_hops": 2,
  "node_filter": {
    "entity_types": ["Publication", "Disease"]
  },
  "edge_filter": {
    "predicates": ["AUTHORED", "DISCUSSES"]
  }
}
```

Result: BFS expands from both researchers simultaneously. The returned subgraph is the union
of both neighborhoods. Full data on Publications and Diseases they connect to; full provenance
on AUTHORED and DISCUSSES edges. Everything else is stubbed. Nodes reachable from both seeds
appear once, making shared connections directly visible.

---

#### Example 4: Widen traversal to include disputed claims

You're specifically investigating disagreement — what did characters doubt or later retract? —
so the default `asserted_true`-only traversal would hide exactly what you're looking for.

```json
{
  "seeds": ["wiki:Sherlock_Holmes"],
  "max_hops": 2,
  "truth_status": ["asserted_true", "disputed", "hypothetical", "retracted"]
}
```

Result: BFS now crosses edges of any of the four listed statuses, so statements Holmes raised
as hypotheses or that other characters disputed are reachable and appear in the subgraph — not
just settled facts. Compare to omitting `truth_status`, which would silently prune these paths
before they ever reach `max_hops`.

---

#### Example 5: Follow a single relationship to its fixed point

You want every location transitively part of Baker Street's neighborhood, with no bound on how
many hops that takes and no interest in any other relationship type along the way.

```json
{
  "start": "wiki:Baker_Street",
  "predicate": "PartOf"
}
```

Result: a flat list of every entity reachable by following only `PartOf` edges outward,
repeated until no new entities are found. No layering, no `max_hops`, no filters — this is a
lighter-weight primitive than `bfs_query()`, intended for exactly this one shape of question.

---

#### Example 6: Reconstruct the evidence available before a revelation

You want to know what the graph supported *before* a specific narrative point, not what it
supports now — e.g. auditing whether a conclusion was foreshadowed or only became knowable
later.

```json
{
  "seeds": ["wiki:Irene_Adler"],
  "max_hops": 1,
  "as_of": 485,
  "edge_filter": {
    "predicates": ["Possesses", "Involves"]
  }
}
```

Result: only `Possesses`/`Involves` statements asserted at or before narrative position 485 are
included, with full data on those two predicates. A `Possesses(Irene, photograph)` statement
extracted later never appears — the query reconstructs the pre-revelation evidence base rather
than the current state.

---

#### Example 7: Audit every disputed or hypothetical statement in the graph

You want a graph-wide list of unsettled claims, not a neighborhood around any particular
entity — a `scan_query()` with no seed.

```json
{
  "truth_status": ["disputed", "hypothetical"]
}
```

Result: every statement carrying either status, wherever it sits in the graph, returned in
full. There's no `max_hops` and no presentation filter to specify — everything matching is
exactly what was asked for.

---

#### Example 8: Surface a disguised identity without knowing which direction was asserted

You have an entity ID and want its true identity, but you don't know (or don't want to guess)
whether the graph asserts `DisguisedAs` from the real identity or `HasTrueIdentity` from the
alias — they're declared as `Inverse`s of each other, and only one direction may have been
extracted.

```json
{
  "seeds": ["wiki:Nonconformist_Clergyman"],
  "max_hops": 1,
  "expand_traits": ["Inverse"]
}
```

Result: if only `DisguisedAs(Holmes, Nonconformist_Clergyman)` was asserted, this query still
surfaces `HasTrueIdentity(Nonconformist_Clergyman, Holmes)` from the seed, computed at query
time and marked `derived_via: "Inverse(DisguisedAs)"` — no need to issue a second query in the
other direction or check which predicate the graph happened to extract.

---

## Design Considerations

### Topology and presentation are orthogonal — except for traversal filters

The subgraph returned by a BFS query is determined by `seeds`, `max_hops`, and the traversal
filters (`truth_status`, `as_of`, `expand_traits`). `node_filter` and `edge_filter` have no
effect on which nodes or edges are included — they only control how much data each item
carries in the response. This means the LLM always sees an accurate picture of the graph's
topology *for the traversal filters it selected*, regardless of what it filtered for
presentation. A stub node is not a missing node; it is a node whose full metadata was not
requested. The traversal filters are the deliberate exception: each is a topology decision
(which edges are traversable, or which extra edges are surfaced) expressed as a query
parameter, not a presentation decision, precisely so that an LLM can't confuse "this claim's
details are hidden" with "this claim isn't reachable at all."

### Why stubs rather than omission

Omitting non-matching nodes entirely would produce a misleading picture of the graph. If
Dr. Jones appears as a stub rather than disappearing, the LLM knows that Stewart has a
connection to another person in the graph, and can issue a follow-up query for Jones if needed.
Omission would make the graph appear sparser than it is, causing the LLM to miss connections
it doesn't know to ask about.

### Edge provenance is expensive context

A single edge with strong multi-source support may carry a long provenance list — source
documents, confidence scores, evidence types, extraction methods. Returning full provenance on
every edge in a two-hop neighborhood would dominate the context window on most queries. The
`edge_filter` gives the LLM precise control over where that cost is paid.

### Multiple seeds enable relational queries

Accepting an array of seeds rather than a single seed allows the LLM to express relational
questions — "what do these entities have in common?" — without requiring a specialized query
type. The union semantics are simple to implement and simple to reason about.

### Filters are independently optional

`node_filter` and `edge_filter` compose independently. You can request full node data with
stub edges (useful when you want entity details but not provenance), full edge provenance with
stub nodes (useful when you want to audit support for a relationship without loading entity
metadata), both (for focused high-detail queries), or neither (for small graphs or debugging).
No special cases are required.

### BFS depth guidance

Depth 1 is appropriate for direct relationships: an author's publications, a drug's known
indications, a gene's associated diseases. Depth 2 surfaces indirect connections: diseases
associated with genes that a drug targets, co-authors of papers a researcher has written.
Depth 3 and beyond can return very large subgraphs on well-connected nodes and should be
used with targeted filters. When in doubt, start at depth 1 and increase.

### Truth status defaults closed, not open

A knowledge graph extracted from narrative or claim-based sources will contain statements that
are hypothetical, disputed, or later retracted — these are real, meaningful nodes, but treating
them as equivalent to settled fact by default would make the LLM's picture of the graph
unreliable in a way that's hard to detect after the fact. Defaulting `truth_status` to
`["asserted_true"]` means an LLM has to opt into uncertainty rather than opt out of it, which
matches how most questions ("what does X possess," not "what might X possess") are actually
asked.

### Reifying relationships enables statements about statements

Modeling a relationship as a node rather than a plain edge costs one extra hop per relationship
crossed, but buys the ability for a statement to be the subject or object of another statement.
Without reification, there's no way to represent "Watson doubts Holmes possesses the cigar
case" as data — the doubt has nothing to attach to. With reification, the doubted claim is just
another node that a second statement can point at. Graphs that don't need meta-statements can
skip this and keep plain edges; graphs modeling claims, testimony, or disputed evidence
generally need it.

### Transitive closure is a narrower, cheaper companion to BFS

BFS answers "what's near this node, considering multiple relationship types, out to N hops."
Transitive closure answers a narrower question — "what's reachable via this one relationship,
however many hops that takes" — and can answer it more cheaply because it doesn't need to track
layers, multiple predicates, or per-node/edge presentation filters. Offering both means an LLM
doesn't have to approximate a fixed-point query with a large, guessed `max_hops` value on
`bfs_query()`, which would be both less accurate (still bounded) and more expensive (returns a
full subgraph instead of an ID list).

### Traversal filters can compose without sharing a default

`truth_status` defaults closed (`asserted_true` only) because most questions assume settled
fact. `as_of` defaults open (no cutoff) because there's no similarly safe default point in
time — "as of when" only makes sense once a caller supplies one. The two filters answer
different questions (how reliable vs. how recent) and are designed to compose, so a query can
restrict by both, either, or neither without one silently overriding the other.

### Scan queries trade locality for completeness

A neighborhood query is bounded by construction — `max_hops` guarantees the response can't grow
just because the graph as a whole is large. `scan_query()` has no such bound: it can return
every match in the graph. That's the right trade when the question is inherently global ("find
every X"), but it puts the burden on the caller to narrow the type/predicate/status filters
enough that the result is a useful list rather than a full graph dump. There's no presentation
filter to fall back on here, because there's no neighborhood surrounding the matches to stub.

### Query-time trait expansion is bounded by decidability, not by convenience

The three named traits are eligible for `expand_traits` specifically because their rule shapes
are guaranteed to be cheap and terminating — single predicate, no function symbols, no
negation. A rule that needs a string test or spans multiple predicates doesn't get this
treatment no matter how useful it would be, because there's no way to guarantee it terminates
or stays cheap at query time. The line is deliberately drawn at "is this rule structurally safe
to evaluate on every query," not "how useful would this be" — usefulness beyond that line is
what a write-time inference engine and `extraction_method="inferred"` materialization are for.
