# Entity-anchored requirement surface query A/B

Status: development-only. Runtime/canonical promotion is prohibited in this cycle.

## Problem

The frozen planner correctly enumerates two requirements for the `광휘의 행로`
question, but emits opaque English relation labels and the generic value type
`amount`. The official guide chunk already contains both literal answers. Segment
selection nevertheless ranks a heading or a neighboring table row above the answer
sentence.

## Arm 0

The frozen contextual answer-unit v3.2.5 plus the development-only official entity
anchor v3.3.0. The entity anchor is safe but did not recover either literal answer.

## Arm 1

Keep the planner requirements, retrieval, source route, chunks, thresholds, K, and
assembler unchanged. When all of the following structural conditions hold, use the
two exact Korean requirement spans from the question only as the segment-reranker
queries:

1. exactly two planner requirements;
2. both share one already verified official entity anchor;
3. the question contains exactly one Korean grammatical coordination boundary;
4. planner requirement order maps to surface order.

The official entity phrase is excluded from the segment query because source and
chunk binding have already happened. This lets the segment query distinguish the
requested relation. The planner subject/relation remain unchanged outside this
scoring view. There are no domain field keywords, translation tables, model calls,
training, reindexing, or gold inputs.

## Pre-fixed gates

- both literal `광휘의 행로` guide spans must be cited;
- frozen 69 and authored adaptive 24 strict regressions: zero;
- literal-evidence regression: zero and target improvement required;
- new false-full: zero;
- exact slices: 100%;
- temporal violations: zero;
- gold, labels, runtime, and canonical artifacts unchanged.

Passing means only `DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED`. The authored set is
adaptive, so it cannot authorize runtime/canonical promotion.
