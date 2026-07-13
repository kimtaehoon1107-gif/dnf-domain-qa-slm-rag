# Partial Decomposition Controlled Run

This run changes only the reviewed Partial decomposition training rows. Keep the base model, legacy instruction, canonical BGE-M3 hybrid chunk-only retrieval, context window, split policy, and training hyperparameters unchanged from checkpoint-250.

Do not run any command below until all 24 human review decisions are complete.

## 1. Freeze and append reviewed rows

```powershell
python src/freeze_partial_decomposition_review.py
python src/build_partial_decomposition_arm.py
```

Both commands verify their input manifests and hashes. The second command writes `domain_train_qa_partial_decomposition_arm.jsonl` without changing the canonical train QA.

## 2. Mine answer-aware negatives

```powershell
python src/mine_hard_negatives.py `
  --qa data/processed/domain_train_qa_partial_decomposition_arm.jsonl `
  --persist-dir outputs/chroma_domain_chunks `
  --exclude-eval-set data/processed/domain_eval_set_expanded.jsonl data/processed/official_eval_set.jsonl data/processed/fresh_paraphrase_eval_set.jsonl data/processed/partial_dev_human_v1.jsonl data/eval/blind_test_v1.jsonl `
  --output data/processed/domain_hard_negatives_partial_decomposition_arm.jsonl `
  --report reports/domain_hard_negatives_partial_decomposition_arm.json `
  --human-review data/review/hard_negative_blind_safe_review_30.csv `
  --reuse-existing data/processed/domain_hard_negatives_answer_filtered_blind_safe_v2.jsonl `
  --model-name BAAI/bge-m3 `
  --rank-mode hybrid `
  --candidate-k 100 `
  --reranker-model BAAI/bge-reranker-v2-m3 `
  --rerank-candidates 20 `
  --reranker-max-length 512 `
  --reranker-batch-size 4 `
  --negatives-per-row 3 `
  --max-evidence-token-recall 0.5
```

The 408 unchanged source rows may reuse their reviewed clean negatives. New decomposition rows must be mined and must receive three safe negatives.

## 3. Build chunk-gold RAFT and balance gates

```powershell
python src/make_raft_dataset.py `
  --docs data/processed/domain_doc_chunks.jsonl `
  --qa data/processed/domain_train_qa_partial_decomposition_arm.jsonl `
  --output data/processed/domain_raft_partial_decomposition_arm_generated.jsonl `
  --exclude-eval-set data/processed/domain_eval_set_expanded.jsonl data/processed/official_eval_set.jsonl data/processed/fresh_paraphrase_eval_set.jsonl data/processed/partial_dev_human_v1.jsonl data/eval/blind_test_v1.jsonl `
  --max-rows 10000 `
  --distractors 2 `
  --gold-text chunk `
  --instruction-mode legacy `
  --hard-negatives data/processed/domain_hard_negatives_partial_decomposition_arm.jsonl `
  --require-hard-negatives `
  --seed 42

python src/build_partial_decomposition_raft_arm.py

python src/make_gate_balanced.py `
  --raft data/processed/domain_raft_partial_decomposition_arm.jsonl `
  --output data/processed/domain_raft_partial_decomposition_arm_gate_balanced.jsonl `
  --oversample 3 `
  --no-oversample-types casual_false_train partial_diverse_train partial_decomposition_train
```

The assembly step preserves all 408 checkpoint-250 baseline RAFT rows and appends only the reviewed decomposition rows. This closes accidental changes caused by duplicate distractor chunks with different IDs. `partial_decomposition_train` then stays at 1x during gate balancing, preventing a small reviewed slice from becoming a new template shortcut.

## 4. Validate before training

```powershell
python src/validate_domain_dataset.py `
  --train-qa data/processed/domain_train_qa_partial_decomposition_arm.jsonl `
  --raft data/processed/domain_raft_partial_decomposition_arm_gate_balanced.jsonl `
  --legacy-eval-set data/processed/official_eval_set.jsonl data/processed/fresh_paraphrase_eval_set.jsonl data/processed/partial_dev_human_v1.jsonl data/eval/blind_test_v1.jsonl `
  --max-doc-chars 900 `
  --max-gold-position-share 0.50 `
  --output reports/domain_dataset_validation_partial_decomposition_arm.json
```

Required: `status=ok`, all parent/chunk/question/context overlap values `0`, gold visibility `1.0`, no missing gold positions, and maximum gold-position share at most `0.50`.

## 5. Train from the same base

Run a dry run first, then remove `--dry-run` without changing any other option.

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-0.5B-Instruct `
  --train-file data/processed/domain_raft_partial_decomposition_arm_gate_balanced.jsonl `
  --output-dir outputs/slm_lora_partial_decomposition_arm `
  --max-doc-chars 900 `
  --max-seq-length 3072 `
  --num-train-epochs 2 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 4 `
  --learning-rate 0.0002 `
  --logging-steps 5 `
  --save-steps 25 `
  --dev-ratio 0.1 `
  --dev-group-by parent_doc_id `
  --eval-steps 25 `
  --seed 42 `
  --gradient-checkpointing `
  --fp16 `
  --dry-run
```

## 6. Compare before opening blind

Evaluate the adapter deterministically on domain, official, fresh_dev, and human Partial dev with `top_k=3`, `candidate_k=100`, `max_doc_chars=900`, no reranker, and the legacy instruction. Produce matching `*_quality.json` reports and a human Partial requirement report.

```powershell
python src/compare_partial_controlled_arm.py `
  --candidate-prefix reports/partial_decomposition_arm `
  --candidate-requirements reports/partial_decomposition_arm_partial_requirements.json `
  --output reports/partial_decomposition_arm_comparison.json
```

Promotion requires all predeclared gates in the comparison report. Even when all gates pass, the script does not query the frozen blind or change Gradio automatically.

## 7. Completed Result

The reviewed arm completed training and deterministic four-dev evaluation. It
is **not promoted** and the frozen blind remains unqueried.

- Human review accepted 23/24 rows (`5 approve / 18 rewrite / 1 reject`).
- The 408 baseline RAFT rows remained byte-identical; only 23 reviewed rows
  were appended.
- Validation passed with all train/eval/blind leakage values at zero, full gold
  visibility, and balanced gold positions.
- Grounded Partial completion improved, but unsupported-slot abstention,
  domain/fresh false joint, domain safety, and domain exact citation regressed.

See `docs/partial_decomposition_arm_results.md` and
`reports/partial_decomposition_arm_comparison.json`. Do not rerun this arm or
open the blind set. The next gate is a Partial-vs-false contrast diagnosis, not
another unmodified training round.
