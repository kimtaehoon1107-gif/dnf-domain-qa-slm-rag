# Federated retrieval A/B

Decision: **NO_GO_FEDERATED_RETRIEVAL**

Integrated index confirmed: **True** (3599 chunks, 8 sources)

| Arm | pool recovery | grounded recovery | grounded | false-full | new false-full | exact | safety leaks | same-parent | reject | realtime | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| arm_a | 0/7 | 0/7 | 73/82 | 9/82 | 0 | 1.0 | 0 | 7/7 | 11/11 | 2/2 | baseline |
| federated_quota | 5/7 | 5/7 | 63/82 | 19/82 | 17 | 1.0 | 0 | 5/7 | 11/11 | 2/2 | FAIL |
| federated_global | 5/7 | 4/7 | 63/82 | 18/82 | 16 | 1.0 | 0 | 5/7 | 11/11 | 2/2 | FAIL |

## Failure taxonomy

- federated_quota: RECOVERED=5; ENUM_MISS=0, SOURCE_SCOPE_MISS=1, RETRIEVAL_MISS=11, ATTRIBUTE_MISMATCH=2, ASSEMBLY_MISS=5
- federated_global: RECOVERED=4; ENUM_MISS=0, SOURCE_SCOPE_MISS=1, RETRIEVAL_MISS=10, ATTRIBUTE_MISMATCH=5, ASSEMBLY_MISS=3

## Cost

- federated_quota: searches=1112, question median/p95=20.762/49.908 ms, reranker pairs=51336, reranker question median/p95=3272.332/5684.36 ms
- federated_global: searches=139, question median/p95=6.294/15.535 ms, reranker pairs=21878, reranker question median/p95=1157.395/2523.75 ms

## Scope

- Hard source filtering was disabled only in the two development arms.
- Frozen planner output, indexes, bge segment reranker, assembler threshold/K, gold, labels, and questions were unchanged.
- No reindex, training, soft-router arm, sealed canary, frozen blind access, or runtime promotion occurred.
