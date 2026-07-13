# Agent Handoff - DNF Domain QA SLM/RAG

## Current Goal

Measurement repair, controlled SLM work, blind-test freeze, clean hard-negative review, human Partial dev, both Phase C context experiments, the reviewed Partial decomposition arm, and the clean step-264 completion check are complete. Checkpoint-250 is retained as the selected clean conservative baseline by early stopping; step-264, parent-window, deterministic-prefix, and Partial decomposition variants are rejected. Canonical retrieval remains BGE-M3 hybrid chunk-only; Gradio remains on `outputs/slm_lora_qwen_domain_v3_3`; reranker remains off; frozen blind remains unevaluated.

The active goal is now to diagnose the Partial-vs-false boundary before any further training. The reviewed decomposition arm answered more grounded slots but overgeneralized `partial` to wholly unsupported questions with distracting retrieved text. Do not start another full training run until a small contrast design explicitly covers that boundary and passes human review and the existing leakage gates.

## Verified State

- Commit containing the measurement repair and controlled data: `67bfad9`.
- Parent-document dev split fix: `3bbbd27`.
- Controlled arms: 408 unique QA groups, 576 input rows, `528 train / 32 dev`, `parent_doc_overlap=0`, skipped rows `0`, 264 steps.
- Final dev loss: control `0.1298`, instruction-only `0.1246`, hard-negative-only `0.1375`. Dev loss did not predict promotion metrics.
- Query-aware evidence window: 900 chars; RAFT visibility `368/368`.
- Reranker A/B: `candidate_k=100`, `BAAI/bge-reranker-v2-m3`, max length 512. Domain hit@3 `0.5222→0.5778`.
- Original blind candidate: `data/review/blind_test_v1_candidate.jsonl`, 100 rows, superseded by the reviewed/frozen release and never queried by retrieval/SLM.
- First blind-review batch completed: 30 rows reviewed, with `29 approved / 1 rejected`. Seven approved rows received evidence-grounded answer/span corrections, including one exact-span newline normalization. The merged working artifact is `data/review/blind_test_v1_candidate_reviewed_30.jsonl`; 70 rows remain in `data/review/blind_test_v1_review_remaining_70.csv`. No retrieval/SLM query has been run on the candidate.
- Assistant-only pre-review of the remaining 70 rows is complete but is not human approval: `51 rewrite / 4 reject / 15 approve`, with `10 high / 45 medium / 15 low` risk. The full proposal is `data/review/blind_test_v1_assistant_pre_review_70.csv`; the human confirmation sample is `data/review/blind_test_v1_human_focus_25.csv` (`10 high + 10 medium + 5 low`). The candidate remains unmodified and unevaluated.
- Risk-stratified human confirmation is complete. The 100-row reviewed working file is `data/review/blind_test_v1_candidate_reviewed_100.jsonl`: `96 approved / 4 rejected`, with approved labels `59 true / 17 partial / 20 false`. Four leakage-safe replacements (`1 true / 3 partial`) were separately reviewed and approved. No candidate or replacement was queried by retrieval/SLM before freeze.
- Blind-test v1 is frozen at `data/eval/blind_test_v1.jsonl`: 100 rows (`60 true / 20 partial / 20 false`), 100 unique IDs/questions, and zero missing chunks, span mismatches, false-with-evidence rows, or direct train/dev/eval parent/chunk/question overlap. SHA-256: `5ba916f8c9c1e78ceaaa160d3b6cf5557a697c12d847f50c63a89e7bb0e0793e`.
- Post-freeze context audit found that v3.3's RAFT exposed `43/45` answerable blind parents and `35/63` exact gold chunks as distractors (`464` occurrences). Controlled arms exposed four replacement parents as distractors. Manifest status is therefore `frozen_unevaluated_requires_clean_retrain`; historical adapters are incompatible with this blind release.
- The first blind-safe hard-negative review is complete: `20 approve / 10 reject`. The 10 rejects exposed eight overly broad source questions, one incorrectly false-labeled answerable question (`casual_false_0001`), and one unsupported-claim question whose scope was ambiguous (`casual_false_0017`). The reviewer marked 23 QA/document pairs as valid alternate evidence rather than negatives.
- Audited corrections are in `data/review/domain_train_qa_blind_safe_corrections_v2.jsonl`. The corrected QA file has 408 rows (`true=277 / partial=44 / false=87`) and passes parent/chunk/question leakage validation.
- The corrected negative map `domain_hard_negatives_answer_filtered_blind_safe_v2.jsonl` reuses 398 unchanged rows and re-mines only the 10 corrected rows. It has 408 rows/1,224 negatives, and all 23 human-rejected QA/document pairs are absent.
- The corrected gate-balanced RAFT `domain_raft_hard_negative_answer_filtered_blind_safe_v2_gate_balanced.jsonl` has 576 rows (`true=277 / partial=92 / false=207`). Blind/eval context overlap is `0`, gold evidence visibility is `369/369`, and validation status is `ok`.
- Targeted follow-up human review passed: all 10 corrected rows have `yes/yes/yes`, `approve`, and reviewer notes; decision inconsistencies are `0`. SHA-256: `36255a81d962911d60c0635f3c6750bf2b7ce921e2dfaae14d183635a6342911`.
- The hard-negative review gate is therefore complete. The next review sheet is `data/review/partial_dev_human_review_20.csv`: 10 domain partial anchors, 6 fresh-dev partial anchors, and 4 cross-topic true anchors. It is dev-only and must not enter train/RAFT.
- Partial-development review passed `20/20`: no missing fields, 20 unique questions, maximum answer length 114 characters, and train/RAFT verbatim question overlap `0`. Frozen output: `data/processed/partial_dev_human_v1.jsonl`, SHA-256 `785e21ee2fcd2d636fc24735ffe0f50f942602f37611f5ededf653ebb8f99aba`.
- Clean training started from `Qwen/Qwen2.5-0.5B-Instruct` with the blind-safe v2 RAFT. Dry-run was `528 train / 32 dev`, parent overlap `0`, skipped rows `0`. The persisted candidate is `checkpoint-250` (`250/264`, epoch `1.894`, dev loss `0.1367`). It is not a completed two-epoch arm; see `reports/clean_answer_filtered_step250_training.json`.
- The command timeout left training alive in the background; a bounded resume attempt did not complete and was stopped. CUDA is currently unavailable to new Python processes, so a driver/system restart is required before evaluation.
- After restart, CUDA recovered and checkpoint-250 was evaluated deterministically with hybrid retrieval, `top_k=3`, `candidate_k=100`, and a 900-character context window. Results: domain citation `0.3667`, partial joint `1/10`, false joint `30/30`; official citation `0.4167`, false joint `6/6`; fresh-dev citation `0.5000`, partial joint `0/6`, false joint `7/8`; human partial-dev citation `0.5000`, partial joint `6/20`.
- Verdict: no promotion and no 264-step completion. Cleaning is validated versus the contaminated hard-negative arm, but it does not beat control jointly: fresh-dev citation and partial joint regress. See `docs/clean_answer_filtered_step250_results.md` and `reports/clean_answer_filtered_step250_evaluation.json`.
- Phase C parent-window A/B is complete and rejected. Retrieval IDs matched exactly. Human partial citation improved `0.50→0.60` but joint stayed `0.30`; fresh-dev citation regressed `0.50→0.4091`, evidence recall regressed `0.3066→0.2612`, and latency rose `3.18s→12.66s`. The window did not add gold coverage. Domain/official expansion was stopped by the predeclared cross-set no-regression gate. See `docs/phase_c_parent_window_ab.md`.
- Phase C deterministic-prefix A/B is complete and rejected. Domain hit@3 fell `0.5222→0.4556` and MRR@10 `0.4239→0.3754`; official hit@10 fell `0.6667→0.5833`; human-partial hit@3 fell `0.90→0.85`; fresh-dev was unchanged. Row-level domain movement was `7 wins / 18 losses / 65 ties`. Generation A/B was skipped after the retrieval gate failed. See `docs/phase_c_contextual_prefix_ab.md`.
- Partial requirement evaluation is implemented and gold-answer oracle validated at `20/20`. Checkpoint-250 answers only `6/31` grounded slots and answers+cites `5/31`; it explicitly abstains on `14/21` unsupported slots but has strict joint success `2/20`. The dominant failure is grounded-slot completion/selection, not insufficient refusal. See `docs/partial_requirement_diagnosis.md`.
- Train-only decomposition candidates are frozen at `24` pending review (`16 event / 8 guide`, 9 train parents). Every candidate is in `data/review/partial_decomposition_train_review_24.csv`; blocked eval/blind parent, chunk, question overlap, missing chunks, span mismatches, and generic refusal rows are all `0`. Manifest status forbids training before review.
- Fresh-dev v3.3 window isolation: 500 chars keeps true/partial/false at `14/16, 2/6, 8/8`; 900 chars yields `12/16, 2/6, 8/8`. The false regression is not a window effect; 900 chars also reduces citation hit `0.6190 -> 0.4286`.
- Reranker top-1 citation baseline: exact citation changes domain `0.3556 -> 0.4556`, official `0.3750 -> 0.2917`, fresh_dev `0.4545 -> 0.6364`; partial joint remains `0`. It is not a global policy or promotion candidate.
- Partial decomposition review is complete: `5 approve / 18 rewrite / 1 reject`; 23 accepted train-only rows are frozen. The reviewed file SHA-256 is `05805d18101b92099f0abff4ce10be5eea9076a27e43b49d8ba14d79749dd60d`.
- The controlled train arm has 431 QA rows. All 408 checkpoint-250 baseline RAFT rows remain byte-identical and only 23 reviewed rows were appended. Gate-balanced RAFT has 599 rows (`true=277 / partial=115 / false=207`).
- Validation passed: train/eval/blind parent, chunk, question, and every RAFT-context overlap are `0`; gold visibility is `392/392`; gold positions are `126/134/132` with maximum share `0.3418`.
- Controlled training completed from Qwen2.5-0.5B-Instruct: 276 steps, `549 train / 34 dev`, parent overlap `0`, skipped rows `0`, final dev loss `0.1571`.
- Deterministic four-dev verdict is **not promoted**. Domain exact citation `33/90 -> 30/90`, false joint `30/30 -> 21/30`, and unsafe safety rows `0/9 -> 2/9`; fresh-dev citation `11/22 -> 15/22` and partial joint `0/6 -> 2/6`, but false joint `7/8 -> 5/8`; human Partial strict requirement joint `2/20 -> 4/20` while explicit unsupported abstention fell `14/21 -> 9/21`.
- Root cause: the 23 new rows teach a supported-fact-plus-personalized-refusal pattern. On wholly unsupported questions, the model treats unrelated retrieved DNF text as the supported half and emits `partial` with an irrelevant citation. Frozen blind remains unqueried. See `docs/partial_decomposition_arm_results.md`.
- The interrupted clean run was resumed from checkpoint-250 and completed at `264/264` with the same data hash, optimizer state, split, seed, and model-affecting hyperparameters. Final dev loss was `0.1345`.
- Step-264 is rejected despite being complete: fresh exact citation fell `11/22 -> 9/22`, human Partial citation `10/20 -> 6/20`, and human Partial joint `6/20 -> 4/20`. False/safety stayed clean and fresh false improved `7/8 -> 8/8`, but the joint quality tradeoff is worse. Checkpoint-250 remains the selected clean baseline. Frozen blind was not queried.

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

This strengthened refusal while damaging evidence selection. `src/mine_hard_negatives.py` now rejects exact/high-overlap answer-like candidates. The superseded pre-blind artifact is:

`data/processed/domain_raft_hard_negative_answer_filtered_gate_balanced.jsonl`

It has 576 rows, gold visibility `1.0`, and exact/high-overlap answer contamination `0`, but the post-freeze audit found blind context overlap (`4` parents and `4` exact blind chunks, all as distractors). It remains untrained and must not be used. Its blind-safe replacement is `data/processed/domain_raft_hard_negative_answer_filtered_blind_safe_gate_balanced.jsonl`.

## Do Not Do

- Do not promote any measurement-round adapter or enable reranker in Gradio.
- Do not call `fresh_paraphrase_eval_set.jsonl` a blind/held-out final test; call it `fresh_dev`.
- Do not run a model on `blind_test_v1_candidate.jsonl` before human review and freeze.
- Do not run retrieval or generation on `data/eval/blind_test_v1.jsonl` during development; it is reserved for one intentional final run.
- Do not add `partial_dev_human_review_20.csv` or its approved output to train/RAFT; it is development evaluation only.
- Do not start the clean-from-base training run until the partial-development review is complete and validated.
- Do not call checkpoint-250 a completed run or promote it. Evaluate it only as an exploratory candidate after CUDA recovers.
- Do not spend another full training run merely to add the final 14 steps; development evidence already rejects this arm for promotion.
- Do not enable sibling-window context in Gradio or canonical generation; it failed the fresh-dev and latency gates.
- Do not promote the deterministic-prefix index or start selective LLM contextual retrieval; the prefix failed cross-set retrieval and neither context experiment justified the complexity.
- Do not use source-QA-only dev loss as a document-generalization claim.
- Do not report answerability alone; always pair it with exact citation, partial joint, false joint, and safety.
- Do not promote or serve `outputs/slm_lora_partial_decomposition_arm`; it failed false, safety, citation, and unsupported-abstention gates.
- Do not add more generic Partial rows or rerun the same recipe. The next data proposal must contrast mixed-evidence Partial with wholly unsupported questions under tempting but irrelevant context.
- Do not select `outputs/slm_lora_answer_filtered_blind_safe_v2_completed` merely because it reached step 264. Its lower dev loss accompanied worse citation and Partial behavior.

## Next Actions

1. For fast portfolio completion, freeze checkpoint-250 as the clean conservative baseline and step-264 as the rejected completion check. Do not spend another training run on this recipe.
2. Update the final comparison to distinguish current demo v3.3 from the leakage-safe clean checkpoint-250 baseline; do not make final blind claims for either.
3. Decide whether the portfolio will stop with the documented Partial limitation or fund one final human-reviewed Partial-vs-false contrast arm.
4. If stopping, finish the RAG-only / base SLM+RAG / clean tuned-SLM comparison and README without querying blind. State that no clean adapter passed the blind-opening gate.
5. If continuing, audit the false/unsupported failure families and human-review a small contrast set before any append or retraining.
6. Run the frozen blind exactly once only after a future clean adapter passes every development promotion gate and the full comparison configuration is frozen.

## Deferred / Next Phase (Phase C)

Do not start this phase until the current data review, one clean answer-filtered hard-negative controlled training round, and the evidence-selector diagnosis are complete. Keep the current canonical retrieval configuration and Gradio defaults unchanged throughout these experiments.

1. Parent-context A/B: complete and rejected.
2. Deterministic-contextual-prefix index A/B: complete and rejected.
3. Selective LLM contextual retrieval: not justified by the first two experiments; do not start in the current cycle.

Use the same development sets and report the same metrics for every arm:

- retrieval `hit_rate@k` and `MRR`;
- exact citation;
- evidence support;
- partial joint and false joint;
- latency.

No Phase C result is promoted to canonical or enabled in Gradio without an end-to-end improvement under these shared metrics.

## Authoritative Artifacts

- `docs/controlled_training_results.md`
- `reports/controlled_training_results.json`
- `reports/hard_negative_failure_diagnosis.json`
- `reports/reranker_ab_measurement_fixed.json`
- `docs/evaluation_policy.md`
- `docs/blind_safe_controlled_round.md`
- `docs/clean_answer_filtered_step250_results.md`
- `reports/clean_answer_filtered_step250_evaluation.json`
- `docs/phase_c_parent_window_ab.md`
- `reports/phase_c_parent_window_ab.json`
- `docs/phase_c_contextual_prefix_ab.md`
- `reports/phase_c_contextual_prefix_ab.json`
- `docs/partial_requirement_diagnosis.md`
- `reports/partial_requirement_annotation_manifest.json`
- `reports/clean_answer_filtered_step250_partial_requirements.json`
- `reports/partial_decomposition_train_candidates_manifest.json`
- `docs/partial_decomposition_arm_results.md`
- `reports/partial_decomposition_arm_comparison.json`
- `reports/domain_dataset_validation_partial_decomposition_arm.json`
- `docs/clean_answer_filtered_completed_results.md`
- `reports/clean_answer_filtered_completed_comparison.json`

## Verification

```powershell
python -m unittest discover -s tests -v
python src/run_smoke_tests.py
python src/validate_domain_dataset.py `
  --train-qa data/processed/domain_train_qa_measurement_fixed.jsonl `
  --raft data/processed/domain_raft_hard_negative_answer_filtered_gate_balanced.jsonl `
  --output reports/domain_dataset_validation_hard_negative_answer_filtered.json
```
