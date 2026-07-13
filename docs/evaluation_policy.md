# Evaluation Policy

## Evaluation roles

| Artifact | Role | May guide model changes? | May be reported as final blind performance? |
|---|---|---:|---:|
| `domain_eval_set_expanded.jsonl` | template-rich development benchmark | Yes | No |
| `official_eval_set.jsonl` | legacy compatibility benchmark | Yes | No |
| `fresh_paraphrase_eval_set.jsonl` | adaptive conversational development set (`fresh_dev`) | Yes | No |
| `partial_dev_human_v1.jsonl` | human-authored partial development slice | Yes | No |
| `data/review/blind_test_v1_candidate.jsonl` | pending human-review candidate | No | No |
| `data/eval/blind_test_v1.jsonl` | approved and frozen one-shot final test | No | Yes, once |

`fresh_paraphrase_eval_set.jsonl` was initially held out, but its individual failures have repeatedly guided data and prompt changes. It is therefore an adaptive development set, not an untouched final test. The filename remains unchanged for compatibility; reports must call it `fresh_dev`.

## Blind-test freeze procedure

1. Generate the candidate with `python src/make_blind_test_candidate.py`.
2. Review all 30 rows in `data/review/blind_test_v1_review_sample_30.jsonl` and inspect the remaining rows by label/topic sampling.
3. Reject or rewrite questions that are ambiguous, answerable from the title alone, unnatural, stale without an `as_of_date`, or unsupported by the exact evidence span.
4. Set accepted rows to `review_status: approved`; keep at least 60 true, 20 partial, and 20 false rows if quality allows.
5. Freeze the approved file and record its SHA-256 in a manifest before any model or retrieval evaluation.
6. Run it once for the final report. Subsequent changes informed by its failures require a new blind-test version.

The pending candidate is proactively included in train/RAFT leakage checks, but **must not be queried by a model** before approval and freeze.

The frozen v1 release has SHA-256 `5ba916f8c9c1e78ceaaa160d3b6cf5557a697c12d847f50c63a89e7bb0e0793e`. Its manifest is `reports/blind_test_v1_frozen_manifest.json`; `evaluated=false` must remain unchanged until the single final run is intentionally started.

The human partial-development slice has 20 approved rows and SHA-256 `785e21ee2fcd2d636fc24735ffe0f50f942602f37611f5ededf653ebb8f99aba`. It is development-only and must never be appended to QA train data or RAFT.

Historical adapters are not compatible with this blind release. The v3.3 training RAFT exposed 43/45 answerable blind parent documents as distractor context. Before the one-shot evaluation, regenerate RAFT with zero blind parent/chunk overlap across **all** gold and distractor documents, then train a new adapter from the base model. Historical adapter results must not be included in the final blind comparison.

## Required reporting

- Retrieval: `hit_rate@1/3/5/10`, `MRR@10`, `candidate_k`, reranker model and max length.
- Generation: answerability by class, exact citation precision/recall, answer-content support, partial joint success, refusal correctness, and unsafe-answer rate.
- Visibility: retrieved-gold rate and usable-gold rate after the same query-aware evidence window used by training/inference.
- Every training run: source SHA-256, grouped split keys, prompt hash, package versions, hyperparameters, checkpoint and losses in `training_manifest.json`.

Do not compare runs that use different eval rows, candidate pools, context windows, or oracle context types as if they were the same benchmark.
