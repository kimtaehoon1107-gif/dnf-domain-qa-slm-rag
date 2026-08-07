# Source-isolated corrective retrieval A/B

## Role

Development-only A/B. This experiment does not change the canonical router,
runtime, corpus, planner, reranker, assembler, gold, or labels.

The inspected failures show that all nine source-scope errors already contain
the answer source in the router's top-two candidate sources. The experiment
therefore keeps each source isolated, runs the frozen retrieval and exact
assembler per source, and permits a per-requirement source replacement only
when the alternative answer unit structurally dominates the baseline. Candidate
chunks from different sources are never pooled before selection.

## Runtime-blind decision contract

- Gold chunk, document, source, answer, and evidence span are scoring-only.
- Candidate sources come only from the frozen route and its existing
  `routing_signals.candidate_sources`, limited to the first two candidates.
- A heading, table marker, image marker, navigation token, or empty segment is
  not an answer-bearing unit.
- The existing one-way value-shape veto remains a negative safety check; a
  matching shape never creates support.
- Per requirement, an alternative source may replace the baseline only when
  its structural vector is no worse in every dimension and strictly better in
  at least one dimension. The vector is answer-bearing status, value-shape
  safety, normalized subject binding, and frozen reranker score.
- The currently selected source is never reassembled by this arm; only a
  different source may replace it. This preserves the frozen same-source span.
- Non-current and account-policy routes retain the existing dedicated temporal
  revision resolver and are not passed through generic isolated retrieval.
- A replacement must be positively answer-bearing, shape-safe, and
  subject-bound. Two equally vetoed or unbound candidates are never resolved by
  reranker score alone.
- An existing partial/abstain response is a safety-preserving result and is not
  upgraded to full by this arm. Corrective retrieval only repairs requirements
  inside a baseline full answer; this prevents a speculative source switch from
  turning an honest partial into a new false-full.
- If no source dominates, the baseline is retained. No global union, raw-score
  fusion, new domain keyword, learned classifier, or per-question rule is used.
- Exact citations keep the frozen parent chunk offsets.

## Pre-registered development gates

The historical score is acceptable-chunk membership. Because a selected chunk
can still expose the wrong segment, the final audit also reports a stricter,
mechanical `evidence_span` containment score. It does not feed gold into the
runtime decision. A development GO additionally requires zero exact-span
regression on the frozen block and exact-span improvement on the authored
diagnostic block.

Existing 95-case development lineage:

- docs-only grounded remains at least 63/69;
- grounded regression versus Q4 is zero;
- mixed span-strict partial remains 13/13 and mixed overclaim remains zero;
- new false-full is zero;
- exact citation is 100%;
- temporal/revision/preview leakage is zero.

Inspected authored validation 24-set (adaptive diagnostic, never sealed):

- all-groups-covered improves beyond 16/24;
- false-full decreases below 6/24;
- new false-full versus the baseline is zero;
- previously passing question regression is zero;
- each source coverage is non-decreasing;
- exact citation is 100%;
- temporal leakage is zero.

Passing both blocks means only `DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED`.
Failure is preserved as `DEVELOPMENT_NO_GO`. Neither outcome authorizes
runtime/canonical promotion.

## Explicit exclusions

- no federated candidate union;
- no source/intent keyword additions;
- no planner rerun for frozen inputs;
- no model training, reindex, natural-language generation, or blind access;
- no gold or acceptable-sibling mutation.
