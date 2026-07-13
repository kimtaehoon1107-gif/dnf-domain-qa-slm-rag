# Blind-Safe Controlled Round

## Status

The final blind v1 release remains frozen and unevaluated. Historical adapters are incompatible because their RAFT contexts exposed blind parent documents as distractors. The next tuned model must start from the base model and use the blind-safe RAFT produced in this round.

## Blind-Safe Hard Negatives and RAFT

| artifact | rows | SHA-256 |
|---|---:|---|
| `domain_hard_negatives_answer_filtered_blind_safe.jsonl` | 408 | `e628709c7bc692fc5994043f6d7edf27ca438403b17384076c92c14b799db2f2` |
| `domain_raft_hard_negative_answer_filtered_blind_safe.jsonl` | 408 | `748c36e9b6defcb6554463faaefd5698e903439ab15ee0ee079ea5fc7b0e8621` |
| `domain_raft_hard_negative_answer_filtered_blind_safe_gate_balanced.jsonl` | 576 | `98a0e3f0f96213e2007889204534fb5a0eb7b85c6ffa8fe38eeb4055159c4c47` |

Verified invariants:

- 408/408 QA rows have three mined hard negatives (1,224 total).
- Answerable rows with evidence-token recall at least `0.5`: `0`; maximum observed recall: `0.4615`.
- Distractors containing the exact evidence span: `0`.
- Blind parent/chunk occurrences across all gold and distractor contexts: `0`.
- Train/dev/eval parent, chunk, and question overlap: `0`.
- Gold evidence visibility at the 900-character training window: `368/368` (`1.0`).

This first artifact remained blocked pending `data/review/hard_negative_blind_safe_review_30.csv`; the review outcome and corrected replacement are recorded below.

## Human Review and Corrected v2

The 30-row review did not pass as-is: `20` rows were approved and `10` were rejected. The failures were not all retriever mistakes. Eight source questions were broad enough that documents labeled as negatives also answered them, `casual_false_0001` was answerable from the official weekly-reward rule, and `casual_false_0017` needed a narrower unsupported-claim scope.

The source artifact was preserved. Corrections were applied into a separate v2 QA file, and the review's 23 `valid_non_answer=no` QA/document pairs became explicit per-question mining blocks.

| artifact | rows | SHA-256 |
|---|---:|---|
| `domain_train_qa_measurement_fixed_blind_safe_v2.jsonl` | 408 | `1cba55061b338a34c691e953a9216f6ecdbccbd8112c10b8fa726c2dddbd484a` |
| `domain_hard_negatives_answer_filtered_blind_safe_v2.jsonl` | 408 | `0c4c5f0e8e6cd7645cb3a43b0c640049376775c1742ca75ebaef13375dce66b5` |
| `domain_raft_hard_negative_answer_filtered_blind_safe_v2.jsonl` | 408 | `ebc4832fc450358072ebadd962b8cb708a6fa20a04844b29de52266526d139f7` |
| `domain_raft_hard_negative_answer_filtered_blind_safe_v2_gate_balanced.jsonl` | 576 | `491951a8b974a2d3c44ccdd8298987d7e4603ba77e662f235bd2ca9cc5eb6def` |

Verified v2 invariants:

- 398 unchanged hard-negative rows were reused; only the 10 corrected rows were re-mined.
- 408/408 rows have three negatives, and the 23 human-rejected pairs have zero overlap with the v2 map.
- Gate-balanced distribution is `true=277 / partial=92 / false=207`.
- Blind/eval gold and distractor context overlap is zero.
- Gold evidence visibility is `369/369` at the 900-character training window.
- `validate_domain_dataset.py` status is `ok`.

The targeted follow-up review passed `10/10`: every candidate received `yes/yes/yes`, `approve`, and a reviewer note. The hard-negative data gate is complete. Training now remains blocked only on the separate human-authored partial-development review; that slice is evaluation-only and will not change the RAFT artifact.

## Fresh-Dev Window Isolation

Same v3.3 adapter, retrieval, seed 42, and 30 fresh-dev rows; only `max_doc_chars` changed.

| context window | overall answerability | true | partial | false | citation hit when retrieved |
|---|---:|---:|---:|---:|---:|
| 500 chars | 0.8000 | 14/16 | 2/6 | 8/8 | 0.6190 |
| 900 chars | 0.7333 | 12/16 | 2/6 | 8/8 | 0.4286 |

Verdict: the control arm's fresh false regression (`8/8` to `5/8`) is not caused by the 900-character window. Both v3.3 window arms keep `8/8` false. The likely cause is the changed training data/split. The 900-character window also harms true classification and citation, so it is not promoted as an inference default.

## Reranker Top-1 Citation Baseline

The original v3.3 reranker generations were reused. Answers and answerability predictions were unchanged; predicted `true/partial` rows cite reranker top-1 and predicted `false` rows cite nothing.

| dev set | model-selected citation | forced reranker top-1 | partial joint | false joint |
|---|---:|---:|---:|---:|
| domain | 0.3556 | 0.4556 | 0.0 | 0.9667 |
| official | 0.3750 | 0.2917 | n/a | 1.0 |
| fresh_dev | 0.4545 | 0.6364 | 0.0 | 1.0 |

Verdict: top-1 citation helps domain and fresh-dev but regresses official and does not recover partial joint success. It is a useful evidence-selector baseline, not a global citation policy and not a canonical/Gradio promotion.

## Next Gate

1. Complete the 20-row human-authored partial development review.
2. Validate and freeze that slice as dev-only data.
3. Train exactly one answer-filtered arm from `Qwen/Qwen2.5-0.5B-Instruct`, not from v3.3.
4. Evaluate domain, official, and fresh-dev under fixed settings.
5. Keep the frozen blind set untouched until the entire model/retrieval configuration is final.
