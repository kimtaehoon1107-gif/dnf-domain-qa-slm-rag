# DNF RAG v3 Controlled Entailment Verifier Pilot

## Decision

- Artifact integrity: **GO**
- Controlled verifier development candidate: **GO**
- Selected controlled candidate: **klue_roberta_base_nli**
- Production verifier: **NO-GO**
- Generator entry: **NO-GO**
- Final benchmark: **NO-GO**

## Controlled results

| model | correct | accuracy | support recall | contradiction recall | insufficient recall | macro F1 |
|---|---:|---:|---:|---:|---:|---:|
| klue_roberta_base_nli | 24/24 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| mdeberta_v3_mnli_xnli | 21/24 | 0.875 | 1.0 | 0.875 | 0.75 | 0.872059 |

The 24 cases contain eight official evidence/gold-answer support pairs, eight explicit single-mutation counterfactuals, and eight cross-source rotated insufficient pairs. These labels are agent-constructed controls and do not estimate natural user-claim performance.

## Observed batch cost

| model | inference seconds | pairs/second | peak CUDA bytes |
|---|---:|---:|---:|
| mdeberta_v3_mnli_xnli | 2.282772 | 10.513534 | 661689856 |
| klue_roberta_base_nli | 0.162973 | 147.263205 | 501466624 |

These values are batch throughput observations, not online p50/p95 latency.

## Limits and next gate

Production remains NO-GO until a separately human-reviewed natural claim set measures support, contradiction, and insufficient cases; confidence calibration and runtime integration also remain unmeasured. No Generator, Router, training, or frozen blind evaluation was run in this cycle.

## Artifacts

- cases: `data/v3/evidence/entailment_control_cases_4d7d0343529edb97a3d678d9e4f71752626bb8c28e26af8f77a51a03e5dc949a.jsonl`
- scores: `data/v3/evidence/entailment_control_scores_f7c818a95d21996ab0f150317b0f43cf93b567b9ad5869ce6d02a0951e03b663.jsonl`
- score manifest: `data/v3/evidence/entailment_control_score_manifest_1c4d63e993cfa8d7fb0726c397d67fc003c12bdca7e5b0ef247602e41d042c3b.json`
