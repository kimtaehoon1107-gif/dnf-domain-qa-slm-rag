# Requirement-query retrieval A/B

Decision: **NO_GO_REQUIREMENT_RETRIEVAL**

This is a development-only A/B. No arm was promoted to canonical or runtime.

## Arm metrics

| arm | retrieval-bound candidate | false-full→grounded | grounded | false-full | new false-full | exact | mean spans | same-parent | reject | realtime safe | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| arm_a | 0/7 | 0/7 | 73/82 | 9/82 | 0 | 1.0 | 2.89781022 | 7/7 | 11/11 | 2/2 | baseline |
| requirement_only | 0/7 | 0/7 | 59/82 | 23/82 | 16 | 1.0 | 2.94244604 | 7/7 | 11/11 | 2/2 | FAIL |
| question_union_requirement | 0/7 | 0/7 | 63/82 | 19/82 | 12 | 1.0 | 2.94244604 | 7/7 | 11/11 | 2/2 | FAIL |

## Cost

- Added requirement searches: 139
- Requirement search median/p95: 5.247 / 10.385 ms
- Requirement-only segment pairs: 25007
- Union segment pairs: 28351

## Guardrails and limits

- Planner outputs, indexes, frozen question candidates, and assembler threshold/K were unchanged.
- Route/filter scope was reconstructed from frozen question candidates; gold source or chunk IDs were not available to retrieval or assembly.
- Reject/realtime cases have no human-gold evidence groups, so the existing assembler evaluation leaves them unsupported; their safety counts are inherited controls, not a new answerability solution.
- The seven retrieval-bound cases use gold IDs only after execution for scoring.
- Wrong-attribute cases remain outside this cycle.
