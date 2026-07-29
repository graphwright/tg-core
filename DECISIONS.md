# Design Decisions

This file records explicit choices made during development — the alternatives
considered, the path taken, and the costs accepted. It exists so that "you, in
three weeks" does not have to re-derive them.

---

## D1. Statement identity: external id vs. content-addressed key (chose path B)

**Date:** 2026-07-14  
**Status:** Decided — path B in force, BFS-QL question deferred (see note)

### The tension

`datalog.Engine` deduplicates statements on a *content-addressed functor key*:

```
_key = f"{predicate.__name__}({subj_id},{obj_id})"
```

`Instance.id` is a separate, caller-supplied string that may be an ontology slug
(`stmt:sib:para4:sent12`), a UUID, or — for engine-derived facts — the functor
key itself. These two identifiers coexist in the engine's `_known` dict but are
not the same thing.

### Path A (not taken)

Make `Instance.id` for every statement *equal* to the functor key. Benefits:
deterministic across load orders; ids are load-bearing and meaningful; `to_python`
output is stable across reloads; the `_key` concept becomes redundant (the engine
deduplicates on `id` directly).

Cost: externally-meaningful statement ids are discarded on ingestion.

### Path B (chosen)

Keep externally-assigned ids. The engine uses `_key` internally for deduplication
and merges provenance from corroborating statements onto the **first-seen** record.
The first-seen id survives; all later ids for the same functor key are ignored.

Benefits: corpus-sourced ids like `stmt:sib:para4:sent12` survive ingestion; the
BFS-QL document and data-export formats that assume that shape are not broken.

Costs accepted:

1. **Two identity notions co-exist.** `_key` (dedup handle) and `Instance.id`
   (stable external reference) remain distinct concepts. Every future feature that
   names a statement node must decide which one it means.

2. **First-seen id wins — ingestion order matters.** Load `[hr_row_17, wiki_42]` for
   the same functor and the surviving id is `hr_row_17`. Reverse the list and it is
   `wiki_42`. Graph contents are a function of ingestion order, which complicates
   diffing, caching, and content-addressing later.

3. **`Instance.id` is decorative for statements.** It is not what dedup uses, not
   what `infer()` produces (derived facts use the functor key as their id), and not
   checked for uniqueness within the engine. It is carried and mostly ignored.

4. **`serialize.py` round-trip stability is not guaranteed.** `to_python` output is
   not stable across reloads of the same corpus in a different order.

5. **Mild tension with R9.** R9 says never parse an id to recover type. Path A makes
   ids *derived from* type (the safe direction: construct, don't parse). Path B
   constructs functor keys internally while presenting an unrelated interface
   externally — the safe-direction work happens inside the engine anyway.

### What `Instance.id` means for a statement under path B

> **For ingested (seed) statements:** `id` is the externally-assigned identifier
> provided at construction — an ontology slug, a corpus reference, a UUID, or any
> other stable string the caller chooses. It is immutable after construction (R7)
> and is never parsed by the engine for type or structure (R9). The engine does not
> guarantee it is unique within `_known`; deduplication operates on `_key`, not `id`.
>
> **For engine-derived statements:** `id` is set to `_key(predicate, subj_id, obj_id)`
> because no external id exists. This is the one place where the two notions coincide.

The outstanding question deferred by path B: **what id does BFS-QL return for a
statement node in a query response?** Candidates are `_key` (stable, deterministic,
predicate-namespaced), `Instance.id` (may be a corpus reference), or both. This must
be resolved before the BFS-QL response schema is finalised — do not leave it implicit.

---

## D2. Provenance is a collection — resolved

**Date:** 2026-07-14  
**Status:** Resolved in code; no further action needed

The field is `provenance: tuple[Provenance, ...] | None` on every `BaseStatement`
(see `base.py`). A statement is either *grounded* (one or more complete `Provenance`
records) or *ungrounded* (`None`). Partial provenance is impossible by construction
(`_reject_empty_provenance` rejects an empty tuple).

When multiple ingested statements share the same functor key, the engine *merges*
their provenance tuples onto the surviving record (`_merge_provenance` in
`datalog.py`). Multi-source corroboration is therefore represented without data loss —
both provenance records appear on the merged statement.

There is no single-provenance footgun left here. The earlier concern (silently keeping
only one source's provenance) is resolved.

---

## D3. Recursive traversal in `_closure_topo` and `_match_body` — deferred

**Date:** 2026-07-14  
**Status:** Deferred — acceptable at current scale, must revisit before large graphs

`serialize._closure_topo` visits the instance DAG recursively (one stack frame per
dependency edge). `datalog.Engine._match_body` recurses over rule body literals
(depth = number of literals in the rule body, typically 2–3). Both hit Python's
default recursion limit of 1000.

At Holmes-scale (dozens of instances, rules with 2–3 literals) neither limit is
reachable. If the system is extended to, say, a 1000-node knowledge graph or rules
with long chains, `_closure_topo` would fail first.

The fix is straightforward — replace both with explicit stack loops — but adds
complexity for no current benefit. Accepted as-is. Revisit when the first graph
large enough to trigger it exists.

---

## D4. `Instance.__eq__` is field-wise; id is not an independent uniqueness key — accepted

**Date:** 2026-07-14  
**Status:** Accepted — intentional behaviour

Pydantic's default `__eq__` compares all fields. `serialize._closure_topo` uses this
to detect conflicting id reuse: two instances with the same `id` but different content
raise `ValueError("two distinct instances share id …")`; two instances with the same
`id` and the same content are treated as the same node and deduplicated silently.

Consequence: `id` is not enforced as a primary key independently of content — a
duplicate with identical fields passes. This is intentional. Enforcing strict `id`
uniqueness (error on any duplicate, even equal content) would break patterns where
the same entity is referenced from multiple statements built from separate call sites.

If strict uniqueness ever becomes a requirement, add a graph-level registry that
checks `id` independently before building instances.

---

## D5. `Provenance` has no temporal / `as_of` field — deferred

**Date:** 2026-07-14  
**Status:** Deferred — unresolved upstream of Holmes loading

`Provenance` currently records `source` and `extraction_method`. There is no field
for when the claim was made or observed (`as_of`, `timestamp`, `valid_from`/`valid_to`).

This matters for BFS-QL query responses (which version of a fact is "current"?) and
for the Holmes corpus (some facts are contradicted or superseded across stories). The
field was deliberately omitted because the right shape (a single instant vs. a
validity interval vs. a reference to an external event) is unresolved.

Do not add a `datetime` field speculatively — the wrong shape will calcify. Resolve
the BFS-QL response schema question first (see also D1), then add the temporal field
to `Provenance` in one place.
