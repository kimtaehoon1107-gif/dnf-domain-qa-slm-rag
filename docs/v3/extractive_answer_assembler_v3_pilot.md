# Extractive Answer Assembler v3 mechanical reranker pilot

## Fixed scope

The assembler contains no LLM call. It reuses the domain-validated
`BAAI/bge-reranker-v2-m3` at revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, max length 512, without
training. Retrieval, the stage2 chunk reranker, planner enumeration,
entailment, answerability, temporal policy, and generation are unchanged or
parked.

The input evidence is the unchanged whole-question baseline selected chunk set.
For each frozen requirement the query is exactly `subject + relation`. Human
gold chunk IDs are absent from model scoring and are used only after all segment
scores are frozen.

## Non-overlapping segmentation

Paragraph candidates are removed. Each physical line is handled exactly once:

- a line with at least two pipe delimiters becomes one table-row segment;
- every other non-empty line is split with kiwipiepy sentence boundaries;
- if sentence splitting yields no unit, the exact trimmed physical line is used.

Segments within one chunk must not overlap. Each records `span_id`, `chunk_id`,
`start_char`, `end_char`, and exact source text. Final output is always obtained
by slicing `source[start_char:end_char]`; generated or normalized answer text is
impossible.

## Mechanical scoring and selection

For every evidence-bearing requirement, the frozen reranker scores all segments
from its selected chunks using query `subject + relation`. Candidates are sorted
by descending score, then `chunk_id`, offsets, and `span_id` for deterministic
ties.

For a configuration `(threshold, K)`, the assembler chooses at most the first K
segments whose score is at least the threshold. If none passes, it returns
`unsupported` with the fixed message `문서에서 확인 불가`. This means only that
the supplied evidence has no selected segment; it is not the parked
personal/realtime answerability decision.

## Aggregate-only parameter grid

The full grid is frozen before segment scores are inspected:

- threshold: `0`, `.001`, `.005`, `.01`, `.025`, `.05`, `.1`, `.2`, `.35`,
  `.5`, `.65`, `.8`, `.9`, `.95`;
- K: `1`, `2`, `3`.

All 42 configurations are derived from one immutable score artifact. No
question-specific threshold, K, keyword, query rewrite, or candidate injection
is permitted.

Configuration choice is deterministic. Among full gate passes, maximize dev
evidence-group hits, then combined fully-cited questions, then minimize mean
segments per supported requirement, then prefer smaller K and higher threshold.
If none passes, preserve a development-only NO-GO representative by minimizing
evidence-group regressions, then question regressions, maximizing dev hits, then
combined fully-cited questions, minimizing mean selections, preferring smaller
K, then higher threshold. This fallback does not constitute promotion.

## Gate fixed before output

GO requires every condition:

- adaptive-dev evidence-group hits exceed the canonical 47/59;
- evidence-group strict regression is zero;
- fully-cited-question strict regression is zero;
- fully-cited-question count improves;
- mean selected segments per supported requirement is at most 3;
- exact-slice span validity is 100%;
- malformed output is zero.

Retrieval-bound and selection-bound questions are excluded from the assembler
gate and reported separately. Segment misses remain assembler failures. The
downgraded 32-set and adaptive dev 63 are aggregate development validation only.
A new sealed canary is allowed only after this gate passes.

## Prohibitions

No LLM, free-form generation, training, new keyword list, entailment,
answerability, new canary, or runtime/canonical promotion is part of this cycle.
Frozen blind, v2 artifacts, AGENTS.md, the handoff, src/outputs, and raw data are
out of scope.
