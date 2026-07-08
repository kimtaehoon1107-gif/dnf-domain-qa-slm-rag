# Experiment Report

## Purpose

This report records the current DNF Domain QA SLM/RAG v2 state after the quality-improvement pass. The project is meant to show a portfolio workflow, not just a chatbot:

- official document collection and chunking
- QA/eval schema design
- Label Studio export/import format
- RAG retrieval MVP
- answerability and citation-aware evaluation
- RAFT-style SLM training data
- LoRA/QLoRA training and inference scaffolding
- Gradio demo for RAG-only and tuned-SLM paths

## Data

| Dataset | Rows | Notes |
|---|---:|---|
| `data/raw/docs.jsonl` | 30 | synthetic controlled docs |
| `data/processed/qa_dataset.jsonl` | 100 | synthetic train/dev/test QA |
| `data/processed/eval_set.jsonl` | 30 | synthetic retrieval/answer eval |
| `data/raw/official_docs.jsonl` | 63 | official DNF notice/update/event docs |
| `data/processed/official_doc_chunks.jsonl` | 197 | promoted header-clean fixed 1200-char official chunks for retrieval |
| `data/processed/official_eval_set.jsonl` | 30 | 24 body-fact chunk questions + 6 safety/OOD rows |
| `data/processed/official_train_qa.jsonl` | 41 | train-only official fact QA plus 4 safety/OOD refusal rows |
| `data/processed/official_raft_sample.jsonl` | 41 | RAFT rows with gold/distractor evidence and refusal examples |
| `data/processed/domain_doc_chunks.jsonl` | 1,307 | official + guide chunks for expanded benchmark |
| `data/processed/domain_eval_set_expanded.jsonl` | 120 | true 80, partial 10, false 30 |
| `data/processed/domain_train_qa_expanded.jsonl` | 308 | train-only expanded QA rows after fresh held-out cleanup |
| `data/processed/domain_raft_sample_expanded.jsonl` | 300 | true 222, partial 19, false 59 |
| `outputs/domain_review_samples.csv` | 100 | human-review sample for expanded eval/RAFT quality |

The previous official eval was title-derived and used placeholder expected answers. The current official eval includes `gold_answer`, `evidence_span`, `expected_doc_id`, `expected_chunk_id`, and `expected_chunk_ids`.

## Retrieval Results

Canonical retrieval now uses BGE-M3 embeddings with the `hybrid` rank mode. Full MiniLM/BGE and rank-mode results are recorded in `docs/retrieval_bge_m3_ablation.md`.
Official chunk-size results are recorded in `docs/official_chunking_ablation.md`.

Synthetic:

```powershell
python src/evaluate.py --eval-set data/processed/eval_set.jsonl --persist-dir outputs/chroma --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/eval_report.json
```

Official chunk-level:

```powershell
python src/evaluate.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_report.json
```

| Eval set | answerable | match scope | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---|---:|---:|---:|---:|
| synthetic | 28 | parent doc | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| official | 24 | chunk | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| domain expanded | 90 | chunk | 0.2556 | 0.3556 | 0.3778 | 0.3050 |

Interpretation: BGE-M3 + hybrid substantially improves the official chunk benchmark over the previous MiniLM lexical baseline. The header-clean fixed 1200-char chunking scheme is now canonical. Hit@5 and reranking remain the next retrieval bottlenecks.

Best chunking variant so far:

| Variant | answerable | match scope | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---|---:|---:|---:|---:|
| fixed 1200 + BGE-M3 + hybrid | 24 | chunk | 0.3333 | 0.6667 | 0.7500 | 0.4889 |

This A/B result came from remapping the previous eval set before header-clean promotion. The official row above is the current canonical metric.

Header-clean/RRF A/B:

| Variant | rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| pre-promotion fixed 1200 | hybrid | 0.2917 | 0.6250 | 0.7083 | 0.4472 |
| pre-promotion fixed 1200 | rrf | 0.2083 | 0.4583 | 0.5000 | 0.3368 |
| promoted no-header fixed 1200 | hybrid | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| no-header fixed 1200 | rrf | 0.3333 | 0.4583 | 0.5833 | 0.4090 |

The no-header variant reduced chunk boilerplate noise from 63/200 chunks to 0/197 chunks. It improved hit@1 and MRR; the hit@5 drop was traced to one top-5 boundary row, so `no-header + hybrid` was promoted. RRF is not promoted because it lowered retrieval recall on this eval.

## Answer-Level Evaluation

Commands:

```powershell
python src/evaluate_answers.py --eval-set data/processed/eval_set.jsonl --persist-dir outputs/chroma --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/answer_eval_report.json
python src/evaluate_answers.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_answer_eval_report.json
```

| Eval set | rows | answerability acc | citation hit | citation precision | citation recall | context relevance | answer relevance | atomic fact support | unsupported rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| synthetic | 30 | 1.0000 | 0.9667 | 0.9667 | 0.9667 | 0.5510 | 0.8078 | 1.0000 | 0 |
| official | 30 | 1.0000 | 0.4667 | 0.4667 | 0.4667 | 0.2853 | 0.4106 | 1.0000 | 0 |
| domain expanded | 120 | 1.0000 | 0.4417 | 0.4417 | 0.4417 | 0.3210 | 0.5142 | 1.0000 | 0 |

Header-clean/RRF answer A/B:

| Variant | rank mode | answerability acc | answerable citation hit | answer relevance | atomic fact support | unsupported rows |
|---|---|---:|---:|---:|---:|---:|
| pre-promotion fixed 1200 | hybrid | 1.0000 | 0.2917 | 0.3841 | 0.9926 | 2 |
| pre-promotion fixed 1200 | rrf | 1.0000 | 0.2083 | 0.4097 | 0.9926 | 2 |
| promoted no-header fixed 1200 | hybrid | 1.0000 | 0.3333 | 0.4106 | 1.0000 | 0 |
| no-header fixed 1200 | rrf | 1.0000 | 0.3333 | 0.4780 | 1.0000 | 0 |

Changes in this pass:

- citation comparison uses chunk IDs when `expected_chunk_ids` are present.
- the RAG-only placeholder cites only the evidence actually used for its answer.
- boilerplate prefixes no longer pollute atomic fact scoring.
- placeholder expected answers are treated as non-informative when present.
- answerability now rejects prompt-injection, exploit, OOD, realtime, and personal-account questions before evidence copying.
- expanded eval/RAFT question generation now avoids comma-anchor questions and noisy footer/nickname-list spans; review samples are exported to `outputs/domain_review_samples.csv`.

## Label Classifier Baseline

```powershell
python src/train_label_classifiers.py --qa data/processed/qa_dataset.jsonl --output outputs/label_classifier_report.json
```

Result:

- intent accuracy: 0.5333
- answerability accuracy: 0.8000

The script now evaluates both dev and test splits when present, while keeping a primary accuracy field for compatibility.

## RAFT and SLM Training Path

Official RAFT regeneration:

```powershell
python src/make_raft_dataset.py --docs data/processed/official_doc_chunks.jsonl --qa data/processed/official_train_qa.jsonl --exclude-eval-set data/processed/official_eval_set.jsonl --output data/processed/official_raft_sample.jsonl --max-rows 52
```

Observed:

- rows: 41
- excluded eval chunks: 24
- excluded eval parent docs: 24
- chunk leakage: 0
- parent-doc leakage: 0
- generic answers: 0
- refusal rows: 4

LoRA dry-run:

```powershell
python src/finetune_lora.py --train-file data/processed/official_raft_sample.jsonl --output-dir outputs/slm_lora --dry-run
```

Observed:

- rows: 41
- answerability: `true=37`, `false=4`
- average training text chars: 2186.71
- max training text chars: 2860
- loss masking: `completion_only_after_### Answer`

Expanded domain LoRA dry-run:

```powershell
python src/finetune_lora.py --train-file data/processed/domain_raft_sample_expanded.jsonl --output-dir outputs/slm_lora_domain --dry-run
```

Observed:

- rows: 300
- answerability: `true=222`, `partial=19`, `false=59`
- average training text chars: 1404.77
- max training text chars: 2815
- loss masking: `completion_only_after_### Answer`

Tiny LoRA smoke:

```powershell
python src/finetune_lora.py --model-name sshleifer/tiny-gpt2 --train-file data/processed/official_raft_sample.jsonl --output-dir outputs/slm_lora_tiny_smoke --limit 2 --max-doc-chars 40 --max-seq-length 1024 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 1 --learning-rate 2e-4 --logging-steps 1 --save-steps 1 --target-modules c_attn,c_proj
```

Observed:

- trained rows: 2
- train loss: 10.82
- adapter output: `outputs/slm_lora_tiny_smoke`

Tiny adapter inference smoke:

```powershell
python src/run_tuned_slm_smoke.py --model-name sshleifer/tiny-gpt2 --adapter-dir outputs/slm_lora_tiny_smoke --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --embedding-model-name BAAI/bge-m3 --rank-mode hybrid --output outputs/tuned_slm_tiny_smoke_eval.json --limit 1 --top-k 2 --max-doc-chars 40 --max-new-tokens 16
```

Observed:

- rows: 1
- adapter loaded successfully
- generation path executed

This is a path smoke only. It does not indicate DNF answer quality.

## Gradio Demo

`app/gradio_app.py` now supports:

- `RAG-only`
- `Tuned SLM`
- `LLM-RAG` reserved mode

Tuned SLM mode reads:

- `TUNED_SLM_MODEL`
- `TUNED_SLM_ADAPTER_DIR`

If no tuned adapter is configured, the UI returns a clear configuration error instead of silently pretending to benchmark a tuned model.

## Smoke Tests

```powershell
python -m compileall -q src app
python src/run_smoke_tests.py
```

Observed:

```json
{
  "smoke_tests": "ok"
}
```

Additional integrity check:

```json
{
  "official_eval_integrity": "ok",
  "eval_rows": 30,
  "train_rows": 41,
  "raft_rows": 41
}
```

## Current Limitations

- Official fact questions are heuristic-generated and still need human review.
- The header-clean fixed 1200-char official chunking variant is now canonical, including remapped eval/train QA, regenerated RAFT, and rebuilt Chroma index.
- Expanded domain eval/RAFT now exists and validates cleanly with domain, official, and fresh paraphrase eval held out, but a 50-100 row human review pass is still needed before strong SLM quality claims.
- Qwen LoRA smoke is a plumbing check, not a performance claim.
- LLM-RAG mode is reserved in the Gradio UI but not connected to an external local/API LLM yet.
