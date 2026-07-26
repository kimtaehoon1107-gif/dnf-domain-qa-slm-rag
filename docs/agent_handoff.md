# Agent Handoff - DNF Domain QA SLM/RAG

## 2026-07-27 Product-router freeze and semantic-binding diagnostics

- Commit `7e38005` freezes the current product router, native Ollama protocol,
  and requirement-aware evidence reduction. Tests at freeze: v3 `702 passed`
  plus `54` subtests; legacy `72 passed`.
- The official sealed one-shot remains `37/64`. No artifact was rewritten and
  no new generalization or production score is claimed.
- Slots 8 and 41 are recorded in a separate reviewed equivalent-evidence
  addendum. The sealed file remains byte-identical.
- The narrow same-evidence-group sufficiency gate was measured in shadow only:
  `21/96` requirements were assessable and only slots `5,7` would trigger.
  Slot 7 is a correct unsupported case, so real fallback retrieval remains
  disabled and deferred.
- Verifier-only replay over the adaptive product-router run changed five wrong
  supported cases (`1,6,60,61,63`) into safe abstentions, with score
  `50/64 -> 50/64`, regressions `0`, new model calls `0`, and retrieval calls
  `0`.
- The new hard checks bind policy subject/revision/effective date and monthly
  month/record/attribute/value. This is a safety diagnostic, not a promotion.
- A replay of an older requirement-reduction artifact reports slot 47 as a
  regression only because its stored `E19` no longer exists in the rebuilt
  prompt namespace. Do not attribute that protocol-incompatible replay result
  to the new binding checks.

See `reports/v3/product_router_semantic_binding_round_20260727.md`.

## 2026-07-25 Latest pipeline full-64 adaptive diagnostic

The current temporal-role prompt, relation-group/currency verifier, table
row-subject binding, and table-only prompt compression were run with 64 new
Qwen3 8B calls over the stored candidate pools.

- Official sealed one-shot remains `37/64`.
- Verifier-only replay of the original outputs remains `43/64`.
- Latest new-generation adaptive diagnostic is `45/64`.
- Approved direct evidence is `35/64`, verifier overreject `5`, generation
  errors `3`, mean/p95 latency `15.76s / 37.20s`.
- Against verifier-only v2: wins `9,10,39,53,55,61`; regressions
  `12,41,43,63`.
- Automatic false-full flags are `31,47,63`. Slots 31 and 47 remain frozen-gold
  omission candidates; slot 63 is a source-reviewed real semantic false-full.
- Slot 9 is correct in this full run but varied to `unsupported` in targeted
  retries. Slot 49 remains correct with exact row citation and 2,578 input
  tokens.
- Overall promotion verdict: **NO-GO**. Do not tune further on these 64 cases.

See:
`reports/v3/typed_evidence_ref_latest_pipeline_qwen3_8b_full64_20260725.md`.

## 2026-07-25 Typed evidence-ref verifier addendum

최신 v3 일반화-64 작업은 아래 인계 문서를 먼저 확인한다.

- `reports/v3/typed_evidence_ref_relation_group_currency_handoff_20260725.md`

핵심 상태:

- 공식 봉인 one-shot은 계속 `37/64`이며 수정하지 않았다.
- 동일한 저장 출력에 relation-group boolean 및 currency-unit verifier를
  사후 적용하면 `43/64`, 직접 근거 `37/64`, overreject `8`, 회귀 `0`이다.
- 새 LLM 호출과 검색 재실행은 없으므로 `43/64`는 공식 새 기준선이 아니라
  verifier-only post-hoc diagnostic이다.
- 자동 false-full flag는 split `2`, Typed `1`이었으나 공식 출처 재검수상
  split 31번과 Typed 47번은 gold 허용 근거 누락 후보이며, 확인된 실제
  relation/column false-full은 split 55번 1건이다.
- 따라서 향후 보고에서는 `자동 frozen-gold false-full flag`와
  `공식 출처 재검수상 실제 false-full`을 분리한다.

## Current Goal

The final portfolio cycle is closed. Canonical retrieval is BGE-M3 hybrid
chunk-only (`top_k=3`, `candidate_k=100`, 900-character query window), the
legacy prompt is frozen, and reranker/parent-window/contextual-prefix variants
remain rejected. One final blind-safe random-control run completed `264/264`
steps. The frozen checkpoint rule selects its `checkpoint-250` as the clean
development baseline, but neither checkpoint passed the fresh/human
blind-opening gates. The frozen blind was not queried and no additional
training cycle is allowed in this release.

Gradio defaults to RAG-only. Tuned mode now points to
`outputs/slm_lora_random_control_blind_safe_final/checkpoint-250`, while base
Qwen + RAG is available as a comparison mode. This is a development demo, not
a blind-validated production model. See `docs/final_release_results.md` and
`reports/final_dev_system_comparison.json`.

## Verified State

- Final blind-safe QA: 408 rows. Final gate-balanced random-control RAFT: 576
  rows (`277 true / 92 partial / 207 false`). Every train/dev/eval/blind
  parent, chunk, question, and RAFT-context overlap is `0`; gold visibility is
  `369/369`; gold positions are `117/124/128`; exact/high-overlap distractor
  contamination is `0` across 1,359 distractors.
- Final training: Qwen2.5-0.5B, `528 train / 32 dev`, parent overlap `0`, two
  epochs, `264/264`, final dev loss `0.1300`, skipped rows `0`.
- Frozen checkpoint verdict: checkpoint-250 beats step 264 on the ordered
  citation/Partial tuple. It scores fresh exact `14/22`, Partial joint `3/6`,
  false joint `5/8`; human exact `12/20`, Partial joint `8/20`, strict
  requirement joint `3/20`.
- Blind gate failure: fresh false requires `7/8` but is `5/8`; explicit
  unsupported abstention requires `14/21` but is `8/21`. Step 264 also fails
  both. Domain/official expansion and frozen blind execution were skipped by
  protocol.
- Final dev-only three-arm comparison is complete. RAG-only cannot express
  Partial; base Qwen has schema compliance `0/30` and unsafe raw answers `2/2`;
  clean tuned Qwen has schema `30/30`, fresh exact `14/22`, and human Partial
  joint `8/20`, but fails refusal gates.

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
- Do not call the historical `slm_lora_answer_filtered_blind_safe_v2_parent_group/checkpoint-250` a completed run or promote it; that warning is separate from the final random-control run.
- Do not spend another full training run on the historical answer-filtered recipe merely to add its final 14 steps; development evidence already rejected that arm.
- Do not enable sibling-window context in Gradio or canonical generation; it failed the fresh-dev and latency gates.
- Do not promote the deterministic-prefix index or start selective LLM contextual retrieval; the prefix failed cross-set retrieval and neither context experiment justified the complexity.
- Do not use source-QA-only dev loss as a document-generalization claim.
- Do not report answerability alone; always pair it with exact citation, partial joint, false joint, and safety.
- Do not promote or serve `outputs/slm_lora_partial_decomposition_arm`; it failed false, safety, citation, and unsupported-abstention gates.
- Do not add more generic Partial rows or rerun the same recipe. The next data proposal must contrast mixed-evidence Partial with wholly unsupported questions under tempting but irrelevant context.
- Do not select `outputs/slm_lora_answer_filtered_blind_safe_v2_completed` merely because it reached step 264. Its lower dev loss accompanied worse citation and Partial behavior.

## Next Actions

1. Do not run another training, retrieval, prompt, or blind experiment in this release.
2. Preserve `checkpoint-250` only as the clean development baseline and keep the Gradio default on RAG-only.
3. Treat `docs/final_release_results.md`, `reports/final_dev_system_comparison.json`, and `reports/final_random_control_release_decision.json` as the final verdict.
4. A future research branch may begin only with a separately approved human-reviewed Partial-vs-unsupported contrast design; it must not rewrite this release's blind decision.

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

- `docs/final_release_results.md`
- `reports/final_dev_system_comparison.json`
- `reports/final_random_control_release_decision.json`
- `reports/final_random_control_training_manifest.json`
- `reports/final_random_control_data_manifest.json`
- `reports/domain_dataset_validation_random_control_blind_safe_final.json`
- `reports/domain_raft_random_control_blind_safe_final_audit.json`
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
