# LoRA/QLoRA Training Scaffold

This folder documents how to move from RAFT-style rows to a tuned SLM adapter.

Current status:

- prompt formatting is shared by training and inference via `src/prompt_format.py`
- `src/finetune_lora.py` masks the prompt/evidence tokens and applies loss only after `### Answer`
- official RAFT rows are generated from `official_train_qa.jsonl`
- held-out official eval parent docs/chunks are excluded from official RAFT

## 1. Dry-run

```powershell
python src/finetune_lora.py `
  --train-file data/processed/official_raft_sample.jsonl `
  --output-dir outputs/slm_lora `
  --dry-run
```

Verified in this workspace:

- rows: 41
- answerability counts: `true=37`, `false=4`
- average training text chars: 2243.90
- max training text chars: 2867
- loss masking: `completion_only_after_### Answer`

## 2. Tiny LoRA Smoke

This verifies adapter training/saving on CPU. It is not a DNF QA quality benchmark.

```powershell
python src/finetune_lora.py `
  --model-name sshleifer/tiny-gpt2 `
  --train-file data/processed/official_raft_sample.jsonl `
  --output-dir outputs/slm_lora_tiny_smoke `
  --limit 2 `
  --max-doc-chars 40 `
  --max-seq-length 1024 `
  --num-train-epochs 1 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 1 `
  --learning-rate 2e-4 `
  --logging-steps 1 `
  --save-steps 1 `
  --target-modules c_attn,c_proj
```

Observed:

- trained rows: 2
- train loss: 10.82
- output adapter: `outputs/slm_lora_tiny_smoke`

## 3. Tiny Inference Smoke

```powershell
python src/run_tuned_slm_smoke.py `
  --model-name sshleifer/tiny-gpt2 `
  --adapter-dir outputs/slm_lora_tiny_smoke `
  --eval-set data/processed/official_eval_set.jsonl `
  --persist-dir outputs/chroma_official_chunks `
  --output outputs/tuned_slm_tiny_smoke_eval.json `
  --limit 1 `
  --top-k 2 `
  --max-doc-chars 40 `
  --max-new-tokens 16
```

Observed:

- rows: 1
- adapter loaded
- generation path executed

## 4. Qwen LoRA Example

Use this only when you are ready for a slower run:

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-0.5B-Instruct `
  --train-file data/processed/official_raft_sample.jsonl `
  --output-dir outputs/slm_lora `
  --max-doc-chars 300 `
  --max-seq-length 2048 `
  --num-train-epochs 1 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 8 `
  --learning-rate 2e-4
```

The previous Qwen 0.5B one-row smoke proved that training and adapter loading work with a Korean-capable small instruct model. It should not be described as quality evidence.

## 5. QLoRA Note

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-1.5B-Instruct `
  --train-file data/processed/official_raft_sample.jsonl `
  --output-dir outputs/slm_qlora `
  --qlora `
  --max-doc-chars 300 `
  --max-seq-length 2048 `
  --num-train-epochs 1 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 8 `
  --learning-rate 2e-4
```

On Windows, regular LoRA or WSL/CUDA is usually easier than QLoRA because `bitsandbytes` support is environment-sensitive.

## 6. Acceptance Gate

Do not claim tuned-SLM quality until all of these are true:

- trained on enough train-only RAFT rows
- evaluated on the same held-out `official_eval_set.jsonl`
- answerability accuracy does not regress materially from RAG-only
- citation hit/recall is competitive with RAG-only
- atomic fact support is stable or improved
- unanswerable/OOD/safety rows are refused
- command, model, adapter path, and eval output are recorded
