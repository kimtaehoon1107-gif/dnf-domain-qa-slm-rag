# SLM Training Stage 1

This stage verifies that the expanded RAFT data can train a small Korean-capable SLM with LoRA on the local CUDA GPU. It is a first tuned-SLM baseline, not a final quality claim.

## Environment

| Check | Result |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Laptop GPU |
| PyTorch | CUDA build detected |
| QLoRA | not used; `bitsandbytes` is not installed on native Windows |
| Training mode | regular LoRA; later stable runs use bf16 |

Windows note: `torch` / `sentence_transformers` must be imported before `chromadb` in retrieval/indexing modules. Loading `chromadb` first and then CUDA PyTorch can trigger a native DLL access violation on this environment. `src/retrieve.py` and `src/build_index.py` intentionally import `torch` and `sentence_transformers` before `chromadb`.

## Verified Commands

Basic checks:

```powershell
python -m compileall src app
python src/run_smoke_tests.py
python src/validate_domain_dataset.py --chunks data/processed/domain_doc_chunks.jsonl --eval-set data/processed/domain_eval_set_expanded.jsonl --train-qa data/processed/domain_train_qa_expanded.jsonl --raft data/processed/domain_raft_sample_expanded.jsonl --output outputs/domain_dataset_validation_report.json
```

30-row probe:

```powershell
python src/finetune_lora.py --model-name Qwen/Qwen2.5-0.5B-Instruct --train-file data/processed/domain_raft_sample_expanded.jsonl --output-dir outputs/slm_lora_qwen_domain_probe --limit 30 --max-doc-chars 700 --max-seq-length 2048 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 4 --learning-rate 2e-4 --logging-steps 1 --save-steps 20 --fp16
```

Full 300-row baseline:

```powershell
python src/finetune_lora.py --model-name Qwen/Qwen2.5-0.5B-Instruct --train-file data/processed/domain_raft_sample_expanded.jsonl --output-dir outputs/slm_lora_qwen_domain --max-doc-chars 700 --max-seq-length 2048 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 8 --learning-rate 2e-4 --logging-steps 5 --save-steps 25 --fp16
```

Cite-first 300-row pass:

```powershell
python src/finetune_lora.py --model-name Qwen/Qwen2.5-0.5B-Instruct --train-file data/processed/domain_raft_sample_expanded.jsonl --output-dir outputs/slm_lora_qwen_domain_citefirst --max-doc-chars 500 --max-seq-length 1536 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 8 --learning-rate 2e-4 --logging-steps 5 --save-steps 25 --bf16
```

Historical gate-balanced 460-row pass:

This command produced the saved failure-analysis baseline before the fresh-exclusion cleanup. Do not rerun it into the same output directory unless you intentionally want to replace that historical adapter.

```powershell
python src/finetune_lora.py --model-name Qwen/Qwen2.5-0.5B-Instruct --train-file data/processed/domain_raft_sample_expanded_gate_balanced.jsonl --output-dir outputs/slm_lora_qwen_domain_gate_balanced --max-doc-chars 500 --max-seq-length 1536 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 4 --learning-rate 2e-4 --logging-steps 10 --save-steps 50 --bf16
```

Fresh-clean gate-balanced v2 command after fresh-exclusion cleanup:

```powershell
python src/finetune_lora.py --model-name Qwen/Qwen2.5-0.5B-Instruct --train-file data/processed/domain_raft_sample_expanded_gate_balanced.jsonl --output-dir outputs/slm_lora_qwen_domain_gate_balanced_v2 --max-doc-chars 500 --max-seq-length 1536 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 4 --learning-rate 2e-4 --logging-steps 10 --save-steps 50 --bf16
```

## Results

| Run | Rows | Epochs | Runtime | Trained rows | Skipped rows | Train loss |
|---|---:|---:|---:|---:|---:|---:|
| probe | 30 | 1 | 125.4s | 30 | 0 | 0.1963 |
| full baseline | 300 | 1 | 382.7s | 300 | 0 | 0.1276 |
| cite-first | 300 | 1 | 1243.0s | 300 | 0 | 0.1102 |
| gate-balanced (historical pre-fresh cleanup) | 460 | 1 | 530.3s | 460 | 0 | 0.0487 |
| gate-balanced v2 (fresh-clean) | 456 | 1 | 1016.0s | 456 | 0 | 0.0531 |

Current fresh-clean gate-balanced dry-run:

| Check | Value |
|---|---:|
| rows | 456 |
| true / partial / false | 222 / 57 / 177 |
| avg training text chars | 1523.58 |
| max training text chars | 2768 |

Full adapter output:

- `outputs/slm_lora_qwen_domain`
- `outputs/slm_lora_qwen_domain_citefirst`
- `outputs/slm_lora_qwen_domain_gate_balanced` (historical pre-fresh-cleanup adapter)
- `outputs/slm_lora_qwen_domain_gate_balanced_v2` (fresh-clean candidate)

## Tuned-SLM Smoke Evaluation

The inference script now supports CUDA generation and keeps chunk IDs in retrieved evidence prompts, matching the RAFT citation format.

10-row chunk-prompt evaluation:

| Metric | Value |
|---|---:|
| rows | 10 |
| answerability field rate | 1.0000 |
| retrieval expected hit rate | 0.4000 |
| avg generation latency | 6.742s |

Longer generation (`max_new_tokens=320`) increased citation-field rows from 1/10 to 3/10, but exact citation hit remained 0/10 on this small slice.

Full 120-row expanded eval after the cite-first pass:

| Metric | Value |
|---|---:|
| rows | 120 |
| answerability field rate | 1.0000 |
| citations field rate | 1.0000 |
| answer field rate | 1.0000 |
| parsed chunk citation rate | 1.0000 |
| citation hit when retrieval hit | 0.7188 |
| citation in retrieved rate | 1.0000 |
| avg answer chars | 147.4 |

Failure found: the cite-first model emitted the expected fields, but parsed `answerability` was `true` for all 120 rows. The answer text sometimes refused correctly, but the structured `answerability` and `citations` fields were wrong on `partial` and `false` rows.

Gate-balanced 120-row expanded eval:

| Metric | Value |
|---|---:|
| rows | 120 |
| answerability accuracy | 1.0000 |
| true accuracy | 1.0000 |
| partial accuracy | 1.0000 |
| false accuracy | 1.0000 |
| answerability field rate | 1.0000 |
| citations field rate | 1.0000 |
| answer field rate | 1.0000 |
| parsed chunk citation rate | 0.7500 |
| citation hit when retrieval hit | 0.7188 |
| citation in retrieved rate | 1.0000 |
| avg answer chars | 134.1 |
| avg generation latency | 5.692s |

Fresh paraphrase/OOD eval:

| Metric | Value |
|---|---:|
| rows | 30 |
| true / partial / false | 16 / 6 / 8 |
| retrieval hit@1 | 0.7727 |
| retrieval hit@3 | 0.9545 |
| retrieval hit@5 | 0.9545 |
| tuned-SLM answerability accuracy | 0.3000 |
| tuned-SLM true accuracy | 0.0000 |
| tuned-SLM partial accuracy | 0.1667 |
| tuned-SLM false accuracy | 1.0000 |
| citation hit when retrieval hit | 0.0476 |

Fresh-clean v2 three-way eval:

| Eval | rows | answerability acc | true acc | partial acc | false acc | citation hit when retrieval hit | avg answer chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| expanded domain | 120 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7188 | 133.7 |
| official fact/safety | 30 | 1.0000 | 1.0000 | n/a | 1.0000 | 0.5333 | 163.5 |
| fresh paraphrase/OOD | 30 | 0.4333 | 0.2500 | 0.1667 | 1.0000 | 0.2381 | 60.3 |

The fresh-clean v2 adapter removes the known official/fresh held-out leakage and improves fresh true accuracy from 0/16 to 4/16 while preserving false/OOD 8/8. It still over-refuses most casual true and partial questions, so it is a cleaner candidate baseline rather than a quality-complete model.

## Interpretation

The local GPU training path is now proven end to end:

1. Expanded RAFT data loads.
2. Completion-only loss masking trains without truncating answer completions.
3. Qwen 0.5B LoRA trains on GPU.
4. The adapter loads and generates on the held-out expanded eval set.

The first tuned-SLM baseline had a clear quality gap: it often copied long retrieved context before emitting `citations:`. Moving citations before the answer fixed field compliance but exposed a new failure: the model marked every row answerable. The gate-balanced passes fixed that on the 120-row expanded eval, but fresh paraphrase/OOD evaluation shows the opposite failure: over-refusal on casual true questions even when retrieval succeeds. The v2 pass is cleaner because held-out question leakage is removed, but it still shows that the next bottleneck is train-only casual true paraphrase coverage. This should be treated as a controlled portfolio experiment, not a production-quality SLM.

## Next SLM Work

1. Add casual true paraphrases to RAFT without using `fresh_paraphrase_eval_set.jsonl`.
2. Rebalance answerability training so false/OOD remains correct but true paraphrases are not over-refused.
3. Manually review the fresh eval generated answers and add a second fresh slice after retraining.
4. Compare `RAG-only`, `Tuned SLM`, and any future `LLM-RAG` mode on the same held-out assumptions.
