# Agent Handoff - DNF Domain QA SLM/RAG

## Current Goal

Measurement repair and the controlled SLM round are complete (2026-07-11). No new adapter passed promotion gates. Gradio remains on `outputs/slm_lora_qwen_domain_v3_3`; reranker remains off.

## Verified State

- Commit containing the measurement repair and controlled data: `67bfad9`.
- Parent-document dev split fix: `3bbbd27`.
- Controlled arms: 408 unique QA groups, 576 input rows, `528 train / 32 dev`, `parent_doc_overlap=0`, skipped rows `0`, 264 steps.
- Final dev loss: control `0.1298`, instruction-only `0.1246`, hard-negative-only `0.1375`. Dev loss did not predict promotion metrics.
- Query-aware evidence window: 900 chars; RAFT visibility `368/368`.
- Reranker A/B: `candidate_k=100`, `BAAI/bge-reranker-v2-m3`, max length 512. Domain hit@3 `0.5222→0.5778`.
- Blind candidate: `data/review/blind_test_v1_candidate.jsonl`, 100 rows, pending human review, never queried by retrieval/SLM.

## Controlled Verdict

| arm | domain citation | domain partial joint | domain false joint | fresh_dev citation | fresh_dev partial joint | fresh_dev false joint |
|---|---:|---:|---:|---:|---:|---:|
| control | 0.3556 | 1/10 | 27/30 | 0.5909 | 2/6 | 5/8 |
| instruction-only | 0.3444 | 0/10 | 29/30 | 0.5909 | 1/6 | 5/8 |
| hard-negative-only | 0.3222 | 2/10 | 30/30 | 0.4091 | 1/6 | 7/8 |

Reranker follow-up: control domain citation `0.4444` but false joint falls to `25/30`; fresh_dev citation stays `0.5909`. Hard-negative under reranking is worse (`0.2778` domain, `0.3182` fresh_dev citation).

## Root Cause Found

The first hard-negative file mislabeled valid evidence as distractor:

- exact gold span inside distractor: 12 instances;
- answerable rows with distractor evidence-token recall ≥0.5: 63/320.

This strengthened refusal while damaging evidence selection. `src/mine_hard_negatives.py` now rejects exact/high-overlap answer-like candidates. The clean future artifact is:

`data/processed/domain_raft_hard_negative_answer_filtered_gate_balanced.jsonl`

It has 576 rows, leakage `0`, gold visibility `1.0`, exact/high-overlap contamination `0`. It has **not** been trained.

## Do Not Do

- Do not promote any measurement-round adapter or enable reranker in Gradio.
- Do not call `fresh_paraphrase_eval_set.jsonl` a blind/held-out final test; call it `fresh_dev`.
- Do not run a model on `blind_test_v1_candidate.jsonl` before human review and freeze.
- Do not train the answer-filtered hard-negative artifact before sampling it for valid alternate evidence.
- Do not use source-QA-only dev loss as a document-generalization claim.
- Do not report answerability alone; always pair it with exact citation, partial joint, false joint, and safety.

## Next Actions

1. Human-review `data/review/blind_test_v1_review_sample_30.jsonl`; rewrite awkward/misaligned questions. Then review/approve all 100 candidate rows and freeze a new SHA-256.
2. Human-review a stratified sample of answer-filtered negatives by label/source type. Confirm each is truly non-answer evidence.
3. Expand partial evaluation with human-written questions before judging further partial changes.
4. Only after steps 1-3, run one answer-filtered hard-negative arm with the same parent split. Keep instruction changes separate.
5. Final blind test is one-shot. Any model change informed by it requires a new blind-test version.

## Authoritative Artifacts

- `docs/controlled_training_results.md`
- `reports/controlled_training_results.json`
- `reports/hard_negative_failure_diagnosis.json`
- `reports/reranker_ab_measurement_fixed.json`
- `docs/evaluation_policy.md`

## Verification

```powershell
python -m unittest discover -s tests -v
python src/run_smoke_tests.py
python src/validate_domain_dataset.py `
  --train-qa data/processed/domain_train_qa_measurement_fixed.jsonl `
  --raft data/processed/domain_raft_hard_negative_answer_filtered_gate_balanced.jsonl `
  --output reports/domain_dataset_validation_hard_negative_answer_filtered.json
```
