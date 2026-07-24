# v3.2 authored validation contract

## Independence and scope

This is a new **authored validation** set, not an independent or sealed
benchmark. The same Codex agent selected source documents, authored questions,
and froze gold evidence before the first run. It must not be described as a
final blind result.

The set contains 24 docs-answerable questions: three from each of the eight
official sources. Previously used gold parents are excluded where possible;
the historical policy questions use explicit revision dates. Questions are not
simple paraphrases of the existing 95 development questions.

## Frozen-before-run metrics

- primary: all required evidence groups cited by acceptable chunk membership;
- exact citation slice rate;
- false-full count: response is full while one or more required groups are absent;
- honest partial/abstain count;
- source-level all-groups coverage;
- temporal/revision/preview/expired exposure violations;
- earliest failure stage using the Q4 audit taxonomy.

## Directional gate

- all-groups-covered questions: at least 18/24;
- every source: at least 2/3 all-groups-covered;
- exact citation slices: 100%;
- temporal/revision exposure violations: 0;
- false-full: at most 3/24.

Small denominators are reported explicitly. Opening failures makes this set
adaptive validation; it may not later be reused as a sealed benchmark.

