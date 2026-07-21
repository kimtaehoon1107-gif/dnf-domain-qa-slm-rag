# Assembler v3 chunk-diverse aggregate repair contract

## Status and motivation

This is a development-only follow-up to the frozen v3 regression diagnostic.
The predeclared K-only grid removed all three regressions only at K=5, which
violated the mean-selection gate. Uniform two/three-segment merge candidates
then caused candidate crowding and was frozen as a NO-GO experiment.

The follow-up tests the aggregate failure mode exposed by that experiment:
several high-scoring segments from one chunk can occupy the entire per-
requirement K budget and suppress evidence from another chunk already selected
by stage2. The rule is source-, question-, gold-, and keyword-independent.
Because it was proposed after viewing adaptive-development aggregate results,
passing this contract permits only a new sealed canary; it is not canonical or
runtime promotion.

## Mechanical selection

Use the original immutable assembler-v3 segment scores. For each requirement:

1. sort candidates by the unchanged reranker score and deterministic tie-break;
2. discard candidates below the global threshold;
3. retain at most the first candidate from each distinct chunk;
4. select at most K distinct chunks;
5. return each chosen segment by its exact source offsets.

There is no merged-segment score, LLM, semantic judge, query rewrite, planner
change, retrieval change, or stage2 reranker change in this repair.

## Aggregate grid and gate

The grid uses the existing thresholds (`0`, `.001`, `.005`, `.01`, `.025`,
`.05`, `.1`, `.2`, `.35`, `.5`, `.65`, `.8`, `.9`, `.95`) and K in `1..3`.
All 42 configurations use one frozen score artifact.

A configuration passes only if:

- adaptive-dev evidence-group hits are at least 54/59;
- eligible fully-cited questions are at least 69/73;
- evidence-group and question strict regression are both zero;
- mean selected segments per supported requirement is at most 3;
- exact-slice validity is 100%, malformed output is zero, and LLM calls are zero.

Among passing configurations, maximize adaptive-dev hits, then fully-cited
questions, then minimize mean selections, prefer smaller K, then the higher
threshold. The downgraded authored canary is reported as adaptive validation,
not as a new sealed result.

## Scope

No individual-question rule, field/intent keyword, model training, 8B/LLM
assembler, answerability, entailment, temporal policy, generator, new canary,
or canonical promotion is allowed in this cycle. Previous v1/v2/v3 and failed
aggregate artifacts remain immutable.
