# From Deduction to Probability: Solving *A Scandal in Bohemia*

*A design note on where the typed-graph mystery demo stands, why deduction has
taken it as far as it can go, and what the probabilistic layer needs to do next.*

---

## 1. Where we are

We imported "A Scandal in Bohemia" into a typed graph and asked it to solve the
story's central puzzle: **where is the incriminating photograph hidden?**

The importer produced a correctly typed graph — 112 entities, 394 statements
across six predicate types (`Involves`, `OccurredAt`, `Possesses`,
`AssociatedWith`, `Knows`, `LocatedIn`). The datalog engine — a bottom-up,
least-fixed-point evaluator — runs a genuine Horn clause over the asserted
facts:

```
PhysicallyIn(o, room) :-
    Possesses(p, o),
    Involves(e, p),
    OccurredAt(e, m),
    AssociatedWith(p, room)
```

In English: an object is physically in a place if its possessor is involved in
some event that occurred at some moment, and that possessor is associated with
the place.

The rule fires. It is correctly typed, range-restricted, and runs through the
engine's real API (`add_facts → add_rule → infer`) with no hard-coded answers
and no fallbacks. And it produces this:

> Deduction narrows **Irene Adler's photograph** to **9 candidate places**:
> Baker Street, the Imperial Opera of Warsaw, **Irene Adler's sitting-room**,
> La Scala, Serpentine Avenue, Serpentine Mews, the Church of St. Monica,
> London, and Warsaw.

The sitting room is in the set. But so are eight other places. **Deduction found
the candidates; it cannot tell us which one is right.**

This is not a failure. It is the exact boundary where one kind of reasoning ends
and another must begin — and seeing it clearly is the whole point of the
exercise.

---

## 2. Why deduction stops here

The reason the photograph lands in nine places at once is worth stating
precisely, because it is a fact about the *data*, not a bug in the rule.

Irene Adler is `AssociatedWith` twelve different locations across the story. The
rule ties the photograph to wherever its possessor is associated — so it
inherits all of her associations. Nothing in the rule prefers the sitting room.

A human reader knows the answer is the sitting room for a specific reason: it is
where Holmes is carried in — feigning injury — at the **very moment** Irene
bolts to check that her most precious possession is safe. The event
`adler_rushes_to_photograph` and the event `holmes_carried_into_sitting_room`
share the moment `holmes_learns_photograph_location`. That temporal coincidence
*is* the clue.

But here is the catch we discovered by inspecting the graph: **that clue is not
in the graph as a fact.** The reveal event carries its location only inside its
name string (`..._into_sitting_room`); it is never expressed as an
event → location edge. The source triplets contain no event-location predicate
at all. So no Horn clause over the existing facts can single out the sitting
room, because the discriminating information was never extracted as structure.

Deduction is monotonic and truth-preserving: it can only tell you what
*necessarily follows* from what you already assert. When the graph
underdetermines the answer, deduction returns the whole admissible set and
stops. That is the honest thing for it to do.

---

## 3. Deduction vs. abduction

What a detective actually does is not deduction. It is **abduction** — inference
to the best explanation.

- **Deduction** runs forward: premises → the conclusion they force.
  *All men are mortal; Socrates is a man; therefore Socrates is mortal.*
- **Abduction** runs backward: an observation → the premise that would best
  explain it. *The grass is wet; rain would explain that; therefore it probably
  rained.*

Abduction is not truth-preserving. The grass could be wet from a sprinkler.
Sherlock's leaps — "the photograph is behind the sliding panel" — are abductive:
he picks the hypothesis that best explains what he observed, not a conclusion
forced by logic. Our datalog engine is purely deductive, which is precisely why
it produces a candidate set and no ranking. The ranking *is* the abductive step,
and it needs machinery deduction does not have.

Several candidate explanations fit the facts. We need a principled way to say
which one is **most likely** — and, just as importantly, to **eliminate** the
ones that contradict other evidence. That is where probability enters.

---

## 4. "I never guess": grounding without certainty

There is a natural objection here, and it comes from Holmes himself. In *The
Sign of Four* he says: *"I never guess. It is a shocking habit — destructive to
the logical faculty."* One might read that as: Holmes wants Boolean certainty; he
would never traffic in probabilities.

That reading is a misinterpretation, and untangling it clarifies the whole
design.

What Holmes condemns is **guessing** — asserting a conclusion with *no evidence
under it*, pulling an answer from nowhere. That is not the opposite of
probability. It is the opposite of *inference from evidence*. A guess is a
probability with no support: a naked prior. What Holmes does is the reverse — he
conditions relentlessly on observed facts and updates.

And his own conclusions are almost never certain. His most famous maxim gives the
game away: *"When you have eliminated the impossible, whatever remains, however
improbable, must be the truth."* That sentence does two things that map exactly
onto probabilistic inference:

1. It **rules possibilities to probability zero** using evidence
   ("eliminated the impossible").
2. It **ranks whatever survives** and accepts the most probable — *"however
   improbable"* is an explicit admission that the answer need not be certain,
   only the best remaining.

Holmes is not a Boolean reasoner who hates probability. He is a Bayesian who
hates *unconditioned* priors. The thing he loathes — the guess — is exactly a
conclusion with no traceable support.

This is why **grounding** matters even once we give up certainty. Our typed
graph already encodes this: every statement carries a `provenance` field, and a
statement is *grounded* when it has a traceable source and *ungrounded* when it
does not. The `truth_status` vocabulary
(`asserted_true`, `asserted_false`, `hypothetical`, `disputed`, `retracted`)
tracks epistemic standing directly. An ungrounded hypothetical with no
provenance is, in Holmes's terms, a guess — inadmissible. A grounded fact
traceable to an observation is evidence — admissible.

When we move to probabilities, grounding does not go away. It becomes the thing
that distinguishes an *evidence-based probability* (a likelihood earned from a
sourced observation) from a *guess dressed up in a number*. The probabilistic
layer must inherit the provenance discipline, not discard it. Uncertainty is
allowed; unsupported assertion is not.

---

## 5. Boolean reasoner vs. Bayesian reasoner

The shift we are making is a shift in what a truth value *is*.

A **Boolean reasoner** works with facts that are true or false. Inference
composes **locally**: to evaluate `A ∧ B` you need only `A` and `B`. Our current
engine is exactly this — least-fixed-point datalog over `asserted_true` facts.

A **Bayesian reasoner** works with facts that carry probabilities in `[0, 1]`.
And here is the conceptual jump that makes this a genuine rethink rather than a
sprinkle of numbers: **probability does not compose locally.** To evaluate
`P(A ∧ B)` you must know whether `A` and `B` share a common cause. If they do,
you cannot simply multiply — they are correlated, and treating them as
independent will over- or under-count the evidence.

This non-locality is the heart of the matter. It means you cannot just decorate
each rule firing with a probability and multiply along the proof. Two shaky
witnesses who are secretly both repeating the same rumor are not independent
corroboration — but a naive local calculation would score them as if they were,
manufacturing false confidence.

The crucial reframing: **the Boolean world is a special case of the
probabilistic one.** Set every probability to exactly 0 or 1 and make every rule
deterministic, and you recover our current least-fixed-point semantics exactly.
So this is a *generalization*, not a demolition. We can keep the Boolean engine
working and add the probabilistic evaluator alongside it — the Boolean version
is simply the corner of the new space where all the weights are crisp. No flag
day.

### Finding the independent variables

The discipline that keeps the non-locality manageable is not "hunt for
independence in the domain." It is sharper: **choose the minimal set of
primitive coin flips such that everything you care about is a deterministic
logical consequence of them.**

Once you have that set, every correlation you were worried about becomes
*derived*, and the engine computes it for you. You never reason about correlation
by hand — you reason only about primitives, and the inference machinery
propagates the dependencies.

The failure mode to watch for: a correlation you *forgot* to represent as a
shared primitive becomes an invisible bug. If two testimonies are both actually
downstream of "Watson misremembered the evening," and you model them as two
independent facts, you will double-count one shaky source as two. The fix is
never to fudge the numbers — it is to name the common cause as its own primitive
fact and have both testimonies *derive* from it. Then the correlation is
structural and correct by construction.

For our mystery, the primitive facts are latent causes: *is the photograph
real?*, *is Irene alarmed by the fire?*, *does she trust the disguised Holmes?*,
*is her instinct to save her most precious possession?* The observable events —
she glances at the hiding place, she moves toward it — are **not** independent
variables. They are *consequences* of those few latent facts, which is exactly
why they are correlated, and why modeling them as primitives would be the error.

---

## 6. ProbLog: probabilistic logic programming

We do not need to invent this from scratch. **ProbLog**, developed by the DTAI
group at KU Leuven, is a mature system that does precisely what we are reaching
for: logic programming where facts carry probabilities.

### The language

A ProbLog program looks like Prolog with probability annotations:

```prolog
0.3::stress(X) :- person(X).
0.2::influences(X, Y) :- person(X), person(Y).

smokes(X) :- stress(X).
smokes(X) :- friend(X, Y), influences(Y, X), smokes(Y).
```

Each annotated fact is an **independent random variable** — a coin flip. This is
the key design decision, and it is exactly the discipline from §5: the
independent primitives are *stipulated by construction* as the annotated facts.
Everything derived inherits its correlation structure from which primitives
appear in its proofs. You do not declare independence; you declare the
primitives, and dependence falls out of the rules.

### The distribution semantics

ProbLog's meaning is defined over **possible worlds**. Each probabilistic fact is
a coin flip; a possible world is one joint outcome of all the flips; the
probability of a query is the summed weight of the worlds in which it is
provable. This is what correctly handles the shared-proof problem — it does not
multiply-and-add locally, it counts worlds globally.

Computing this naively is intractable, so ProbLog compiles the whole program,
plus queries and evidence, into a **weighted Boolean formula** and reduces
inference to **weighted model counting** — a well-studied problem solved with
knowledge-compilation methods (d-DNNF, SDD). We get correct global inference
without hand-rolling any probability arithmetic.

Notice the shape of this: evaluation stops being local rule-by-rule propagation
(what our datalog engine does) and becomes global compilation. That change in
*strategy* — not just in values — is the real depth of the rethink. It is also
exactly the part ProbLog has already solved, which is the argument for routing
through it rather than reinventing it.

### Evidence: the elimination mechanism

ProbLog supports conditioning on evidence:

```prolog
evidence(smokes(angelika), false).
query(smokes(joris)).
```

This is **the Holmes elimination principle, mechanized.** "Irene is not at
location X" becomes `evidence(..., false)`; the marginals over the remaining
candidates renormalize; the ranking updates. Ruling out the impossible and
ranking the improbable remainder — the two halves of the famous maxim — are
`evidence(...)` and marginal computation respectively. The abductive
"eliminate possibilities" behavior we needed lives *inside* the probabilistic
framework; we do not need a separate constraint layer for the basic case.

### Is this hypothesis testing?

Very close in spirit, but not the same machinery.

What Step 4 does is **Bayesian updating**:

- Step 3 gives priors (e.g., `0.85::irene_alarm_response.`).
- Step 4 adds observations as evidence (e.g., `evidence(occurred_at(...), true).`).
- ProbLog computes posteriors by conditioning: from $P(H)$ to $P(H \mid E)$,
  where $H$ is a hypothesis ("the photograph is in place X") and $E$ is what we observed.

Classical null-hypothesis significance testing (NHST) asks a different question:
whether data are surprising under a null model (p-values, reject/fail-to-reject).
Our workflow asks for **direct probabilities over competing hypotheses after
conditioning on evidence**. That is exactly why it feels so rewarding here: it
maps naturally to detective reasoning as explanation-ranking under uncertainty.

### There is a Python library

ProbLog ships as a `pip`-installable Python package (`pip install problog`). The
integration surface is small:

```python
from problog.program import PrologString
from problog import get_evaluatable

model = "0.3::a.  query(a)."
result = get_evaluatable().create_from(PrologString(model)).evaluate()
# -> {a: 0.3}
```

`evaluate()` returns a dict mapping each query term to its probability. That dict
*is* our ranking. The whole boundary between our typed graph and their engine is
one function: **turn `BaseStatement` instances into ProbLog program text.**

The package also offers three things we will likely want later:

- **Decision-Theoretic ProbLog** (`dtproblog`) — marks *decisions* (`?::search_panel`)
  and returns the choice that maximizes expected utility. "Which hiding place do I
  search, given the cost of searching the wrong one?" is a decision under a
  distribution — closer to what a detective actually does than bare marginals.
- **Parameter learning (LFI)** — learns the fact probabilities from examples,
  the principled answer to "where do these numbers come from?" instead of
  hand-assigning reliabilities.
- **Sampling** — draws possible worlds you can inspect, invaluable for debugging
  whether a wrong marginal is an encoding error or a modeling error.

---

## 7. The plan for the next piece of work

The typed structure — the `(T, Φ, V, τ)` model, the Pydantic hierarchy,
domain/range validation, higher-order predication — is **orthogonal** to whether
truth is Boolean or `[0, 1]`. That whole layer survives untouched. What changes
is narrower than it first feels: the *truth valuation* and the *inference
evaluator*.

The lowest-risk path forward:

1. **Keep the Boolean engine and the typed graph exactly as they are.** They are
   correct and proven. The Boolean engine is the crisp-weight corner of the
   probabilistic space, not something to throw away.

2. **Add probabilistic inference as a second, optional evaluator** that reads the
   same `V` and the same rules. For now, implement it by *emitting ProbLog and
   calling their engine*. This validates the modeling before paying for any
   native reimplementation.

3. **Identify the primitive random variables** for the Scandal graph — the
   minimal set of latent coin flips (photograph real, Irene alarmed, trusts the
   disguise, instinct to protect) from which the observable events derive. This
   is the modeling work that makes or breaks the result, and it is where the
   §5 discipline earns its keep.

4. **Encode evidence** — including the missing signal. The reveal-moment
   coincidence that deduction could not use becomes a piece of evidence that
   concentrates probability mass on the sitting room. This is the step that
   finally singles it out.

5. **Rank the nine candidates.** With primitives, rules, and evidence in place,
   `evaluate()` returns marginals over the candidate places, and the sitting room
   should rise to the top — not because we asserted it, but because it is the
   best explanation of the conditioned evidence.

A design fork to decide once the encoding is proven: emit ProbLog text
permanently and accept the dependency, or reimplement the distribution semantics
natively so the typed graph stays the single source of truth with no string
round-trip. That decision can wait until the modeling is validated against their
engine.

### Two known issues to keep in view

- **The `to_python` shared-node bug.** A shared entity is currently emitted
  inline twice rather than once by reference, contradicting the identity
  guarantee the serializer documents (`test_serialize.py` fails on this today).
  Worth fixing independently — and worth confirming the probabilistic layer's
  fact-loading does not inherit the same duplication.

- **The missing event → location edge.** If we want deduction *alone* to single
  out the sitting room, the honest fix is to author the
  `carry_event → sitting_room` fact into the dataset, not to over-tighten the
  rule. The probabilistic route reaches the answer a different way — by
  conditioning on the shared moment — and is the more interesting path.

---

## Summary

Deduction took us to nine honest candidates and correctly refused to guess among
them. Going the rest of the way is abduction — inference to the best explanation
— which needs probability. ProbLog gives us the machinery: annotated facts as
independent primitives, the distribution semantics for correct global inference,
and evidence conditioning as the mechanized form of "eliminate the impossible,
then rank whatever remains." It ships as a Python library with a one-function
integration surface. For readers coming from statistics, see "Is this
hypothesis testing?" above for a concise Bayesian-vs-NHST framing.

Holmes would approve — not because the answer is certain, but because every step
of it is *grounded*. Uncertainty is allowed; guessing is not. That is the
difference between a Boolean reasoner and a Bayesian one, and it is the line our
next piece of work walks.