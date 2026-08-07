# v1/v2 재현 (레거시)


아래 절은 기존 v1/v2 실험의 재현 기록입니다. 현재 Product Free RAG의 실행 방법은 [PORTFOLIO.md §8](PORTFOLIO.md#8-기술-스택과-재현)을 참고하세요.

## Current Scope

- v1 baseline analysis: `docs/v1_baseline_failure_analysis.md`
- data schema: `docs/data_schema.md`
- labeling guide and Label Studio config: `docs/labeling_guide.md`, `labeling/`
- experiment report: `docs/experiment_report.md`
- model comparison report: `docs/model_comparison_report.md`
- final clean release verdict: `docs/final_release_results.md`
- controlled measurement-repair results: `docs/controlled_training_results.md`
- evaluation/blind-test policy: `docs/evaluation_policy.md`
- tuned-SLM failure diagnosis: `docs/tuned_slm_failure_diagnosis.md`
- BGE-M3 retrieval ablation: `docs/retrieval_bge_m3_ablation.md`
- official chunking ablation: `docs/official_chunking_ablation.md`
- header-clean/RRF ablation: `docs/header_clean_rrf_ablation.md`
- dataset expansion Stage 1: `docs/dataset_expansion_stage1.md`
- SLM training Stage 1: `docs/slm_training_stage1.md`
- roadmap status: `docs/end_to_end_roadmap_status.md`
- Gradio demo: `app/gradio_app.py`

## Data

| File | Rows | Purpose |
|---|---:|---|
| `data/raw/docs.jsonl` | 30 | synthetic controlled documents |
| `data/processed/qa_dataset.jsonl` | 100 | synthetic QA labels |
| `data/processed/eval_set.jsonl` | 30 | synthetic eval |
| `data/raw/official_docs.jsonl` | 63 | official DNF docs |
| `data/processed/official_doc_chunks.jsonl` | 197 | promoted header-clean fixed 1200-char official retrieval chunks |
| `data/processed/official_doc_chunks_no_header.jsonl` | 197 | retained header-clean A/B artifact used for promotion |
| `data/processed/official_eval_set.jsonl` | 30 | 24 fact-based chunk eval rows + 6 safety/OOD rows |
| `data/processed/official_train_qa.jsonl` | 41 | train-only official QA rows, including 4 safety/OOD refusal rows |
| `data/processed/official_raft_sample.jsonl` | 41 | official RAFT rows with gold/distractor evidence and refusal examples |
| `data/processed/domain_doc_chunks.jsonl` | 1,307 | official + guide chunks for expanded domain benchmark |
| `data/processed/domain_eval_set_expanded.jsonl` | 120 | expanded held-out eval: true 80, partial 10, false 30 |
| `data/processed/fresh_paraphrase_eval_set.jsonl` | 30 | adaptive conversational dev (`fresh_dev`): true 16, partial 6, false 8 |
| `data/processed/partial_dev_human_v1.jsonl` | 20 | human-reviewed Partial development set; never use for training |
| `data/eval/blind_test_v1.jsonl` | 100 | frozen, reviewed blind set; not queried because final dev gates failed |
| `data/processed/domain_train_qa_expanded.jsonl` | 419 | historical expanded train QA before the measurement quality gate |
| `data/processed/domain_train_qa_measurement_fixed.jsonl` | 408 | quality-gated train QA used by the controlled experiment |
| `data/processed/domain_raft_sample_expanded.jsonl` | 419 | historical expanded RAFT rows |
| `data/processed/domain_raft_sample_expanded_gate_balanced.jsonl` | 593 | historical gate-balanced RAFT rows |
| `data/processed/domain_raft_measurement_fixed_gate_balanced.jsonl` | 576 | control arm: legacy instruction + random distractors |
| `data/processed/domain_raft_instruction_only_gate_balanced.jsonl` | 576 | instruction-only controlled arm |
| `data/processed/domain_raft_hard_negative_only_gate_balanced.jsonl` | 576 | rejected unfiltered hard-negative audit artifact |
| `data/processed/domain_raft_hard_negative_answer_filtered_gate_balanced.jsonl` | 576 | validated future candidate; not trained in this round |
| `data/processed/domain_raft_random_control_blind_safe_final_gate_balanced.jsonl` | 576 | final blind-safe random-control RAFT used for the last clean run |
| `outputs/domain_review_samples.csv` | 100 | review sample for expanded eval/RAFT question quality |
| `labeling/domain_review_tasks.jsonl` | 100 | JSONL review tasks for labeling/rewrite workflows |

The official eval set now uses `gold_answer`, `evidence_span`, `expected_doc_id`, `expected_chunk_id`, and `expected_chunk_ids`. This avoids the previous title-derived placeholder eval.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install training dependencies only when needed:

```powershell
pip install -r requirements-train.txt
```

## Build Indexes

```powershell
python src/build_index.py --docs data/raw/docs.jsonl --persist-dir outputs/chroma --model-name BAAI/bge-m3 --reset
python src/build_index.py --docs data/raw/official_docs.jsonl --persist-dir outputs/chroma_official --model-name BAAI/bge-m3 --reset
python src/build_index.py --docs data/processed/official_doc_chunks.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --reset
python src/build_index.py --docs data/processed/guide_chunks.jsonl --persist-dir outputs/chroma_guide_chunks --model-name BAAI/bge-m3 --reset
python src/build_index.py --docs data/processed/domain_doc_chunks.jsonl --persist-dir outputs/chroma_domain_chunks --model-name BAAI/bge-m3 --reset
```

MiniLM ablation indexes are kept separately as `outputs/chroma_minilm` and `outputs/chroma_official_chunks_minilm`.

## Regenerate Official Eval and Train QA

```powershell
python src/make_official_eval_set.py `
  --chunks data/processed/official_doc_chunks.jsonl `
  --output data/processed/official_eval_set.jsonl `
  --train-output data/processed/official_train_qa.jsonl `
  --answerable-limit 24 `
  --train-limit 48
```

This creates a held-out official eval set and a separate train QA file from different parent documents.

## Regenerate RAFT Data

Synthetic:

```powershell
python src/make_raft_dataset.py `
  --docs data/raw/docs.jsonl `
  --qa data/processed/qa_dataset.jsonl `
  --output data/processed/raft_train_sample.jsonl `
  --max-rows 60
```

Official:

```powershell
python src/make_raft_dataset.py `
  --docs data/processed/official_doc_chunks.jsonl `
  --qa data/processed/official_train_qa.jsonl `
  --exclude-eval-set data/processed/official_eval_set.jsonl `
  --output data/processed/official_raft_sample.jsonl `
  --max-rows 52
```

The official RAFT command excludes held-out eval parent docs/chunks to prevent train/eval leakage.

## Evaluate Retrieval

```powershell
python src/evaluate.py --eval-set data/processed/eval_set.jsonl --persist-dir outputs/chroma --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/eval_report.json
python src/evaluate.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_report.json
```

Current verified retrieval with BGE-M3 + hybrid:

| Eval set | scope | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| synthetic | parent doc | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| official fact eval | chunk | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| domain expanded eval | chunk | 0.2556 | 0.3556 | 0.3778 | 0.3050 |

The official result uses the promoted header-clean fixed 1200-char chunking scheme with BGE-M3 + hybrid ranking. Hit@5 and reranking remain real bottlenecks.

Chunking A/B note:

| Variant | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| official fixed 1200 + BGE-M3 + hybrid | 0.3333 | 0.6667 | 0.7500 | 0.4889 |

The table above is the historical A/B result from remapping the previous eval set before header-clean promotion. The current official metric is the `official fact eval` row above.

Header-clean/RRF A/B:

| Variant | rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| pre-promotion fixed 1200 | hybrid | 0.2917 | 0.6250 | 0.7083 | 0.4472 |
| pre-promotion fixed 1200 | rrf | 0.2083 | 0.4583 | 0.5000 | 0.3368 |
| promoted no-header fixed 1200 | hybrid | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| no-header fixed 1200 | rrf | 0.3333 | 0.4583 | 0.5833 | 0.4090 |

The no-header variant removes board boilerplate from chunks and answers. It was promoted because the hit@5 drop was traced to one top-5 boundary row, while hit@1, MRR, citation, and answer cleanliness improved. RRF is kept as an ablation baseline, not promoted.

## Evaluate Answers

```powershell
python src/evaluate_answers.py --eval-set data/processed/eval_set.jsonl --persist-dir outputs/chroma --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/answer_eval_report.json
python src/evaluate_answers.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_answer_eval_report.json
```

Current verified answer-level summary:

| Eval set | answerability acc | citation hit | citation recall | answer relevance | atomic fact support |
|---|---:|---:|---:|---:|---:|
| synthetic | 1.0000 | 0.9667 | 0.9667 | 0.8078 | 1.0000 |
| official fact eval | 1.0000 | 0.4667 | 0.4667 | 0.4106 | 1.0000 |
| domain expanded eval | 1.0000 | 0.4417 | 0.4417 | 0.5142 | 1.0000 |

The answerability gate now refuses prompt-injection, exploit, OOD, realtime, and personal-account questions before copied retrieval context can turn them into unsupported answers.

## Label Classifier Baseline

```powershell
python src/train_label_classifiers.py --qa data/processed/qa_dataset.jsonl --output outputs/label_classifier_report.json
```

The script uses train/dev/test splits when present.

## Label Studio

```powershell
python src/label_studio_io.py export-tasks `
  --input data/processed/qa_dataset.jsonl `
  --docs data/raw/docs.jsonl `
  --output outputs/label_studio_tasks.json `
  --include-prelabels
```

After exporting annotations from Label Studio:

```powershell
python src/label_studio_io.py convert-export `
  --input exports/label_studio_export.json `
  --output data/processed/labeled_qa_from_label_studio.jsonl
```

## LoRA/QLoRA Scaffold

Dry-run:

```powershell
python src/finetune_lora.py `
  --train-file data/processed/official_raft_sample.jsonl `
  --output-dir outputs/slm_lora `
  --dry-run
```

Current dry-run:

- rows: 41
- answerability counts: `true=37`, `false=4`
- loss masking: `completion_only_after_### Answer`
- train/inference prompt builder: `src/prompt_format.py`

Expanded domain dry-run:

```powershell
python src/finetune_lora.py `
  --train-file data/processed/domain_raft_sample_expanded.jsonl `
  --output-dir outputs/slm_lora_domain `
  --dry-run
```

- rows: 300
- answerability counts: `true=222`, `partial=19`, `false=59`
- loss masking: `completion_only_after_### Answer`

Gate-balanced SLM dry-run:

```powershell
python src/finetune_lora.py `
  --train-file data/processed/domain_raft_sample_expanded_gate_balanced.jsonl `
  --output-dir outputs/slm_lora_domain_gate_balanced `
  --dry-run
```

- rows: 456
- answerability counts: `true=222`, `partial=57`, `false=177`
- purpose: teach structured refusal and empty citations for unsupported questions

Tiny local smoke:

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

Tuned-SLM inference smoke:

```powershell
python src/run_tuned_slm_smoke.py `
  --model-name sshleifer/tiny-gpt2 `
  --adapter-dir outputs/slm_lora_tiny_smoke `
  --eval-set data/processed/official_eval_set.jsonl `
  --persist-dir outputs/chroma_official_chunks `
  --embedding-model-name BAAI/bge-m3 `
  --rank-mode hybrid `
  --output outputs/tuned_slm_tiny_smoke_eval.json `
  --limit 1 `
  --top-k 2 `
  --max-doc-chars 40 `
  --max-new-tokens 16
```

Qwen LoRA smoke from the previous pass is a path check only, not a quality claim.

Qwen 0.5B LoRA Stage 1:

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-0.5B-Instruct `
  --train-file data/processed/domain_raft_sample_expanded.jsonl `
  --output-dir outputs/slm_lora_qwen_domain `
  --max-doc-chars 700 `
  --max-seq-length 2048 `
  --num-train-epochs 1 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 8 `
  --learning-rate 2e-4 `
  --logging-steps 5 `
  --save-steps 25 `
  --fp16
```

Verified:

- trained rows: 300
- skipped truncated rows: 0
- train runtime: 382.7s
- train loss: 0.1276
- adapter: `outputs/slm_lora_qwen_domain`

This is the first tuned-SLM baseline. It proves the local GPU training path, but citation-format compliance still needs improvement before making quality claims.

Qwen 0.5B gate-balanced LoRA historical pass:

The saved adapter below predates the fresh-exclusion cleanup. Keep it as the failure-analysis baseline unless you intentionally want to replace it.

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-0.5B-Instruct `
  --train-file data/processed/domain_raft_sample_expanded_gate_balanced.jsonl `
  --output-dir outputs/slm_lora_qwen_domain_gate_balanced `
  --max-doc-chars 500 `
  --max-seq-length 1536 `
  --num-train-epochs 1 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 4 `
  --learning-rate 2e-4 `
  --logging-steps 10 `
  --save-steps 50 `
  --bf16
```

Verified historical result on `data/processed/domain_eval_set_expanded.jsonl`:

- rows: 120
- answerability accuracy: 1.0000 (`true=80/80`, `partial=10/10`, `false=30/30`)
- field rates: answerability/citations/answer all 1.0000
- citation hit when retrieval hit: 0.7188
- citation in retrieved rate: 1.0000
- average answer length: 134.1 chars
- adapter: `outputs/slm_lora_qwen_domain_gate_balanced`

The earlier cite-first 300-row pass fixed field compliance but marked every eval row as `true`; the gate-balanced pass is the current historical in-distribution tuned-SLM candidate. Its very low training loss should be treated as an overfit warning.

Fresh paraphrase/OOD check:

- eval: `data/processed/fresh_paraphrase_eval_set.jsonl`
- retrieval hit@1 / hit@3 / hit@5: `0.7727 / 0.9545 / 0.9545`
- tuned-SLM answerability accuracy: `0.3000`
- tuned-SLM true accuracy: `0/16`
- tuned-SLM partial accuracy: `1/6`
- tuned-SLM false accuracy: `8/8`

Interpretation: the gate-balanced adapter over-refuses casual true questions even when retrieval finds the expected chunk. The 120/120 expanded-eval score is in-distribution template performance, not proof of general user robustness.

Note: `data/processed/domain_train_qa_expanded.jsonl` and `data/processed/domain_raft_sample_expanded*.jsonl` have since been regenerated with `domain_eval_set_expanded.jsonl`, `official_eval_set.jsonl`, and `fresh_paraphrase_eval_set.jsonl` held out. The existing `outputs/slm_lora_qwen_domain_gate_balanced` adapter predates that fresh-exclusion cleanup and is retained as the failure-analysis baseline; `outputs/slm_lora_qwen_domain_gate_balanced_v2` is the clean candidate.

Fresh-clean gate-balanced v2:

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-0.5B-Instruct `
  --train-file data/processed/domain_raft_sample_expanded_gate_balanced.jsonl `
  --output-dir outputs/slm_lora_qwen_domain_gate_balanced_v2 `
  --max-doc-chars 500 `
  --max-seq-length 1536 `
  --num-train-epochs 1 `
  --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 4 `
  --learning-rate 2e-4 `
  --logging-steps 10 `
  --save-steps 50 `
  --bf16
```

Verified v2 result:

- trained rows: 456
- skipped truncated rows: 0
- train runtime: 1016.0s
- train loss: 0.0531
- adapter: `outputs/slm_lora_qwen_domain_gate_balanced_v2`

Three-eval check:

| Eval | rows | answerability acc | true acc | partial acc | false acc | citation hit when retrieval hit |
|---|---:|---:|---:|---:|---:|---:|
| domain expanded | 120 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7188 |
| official fact/safety | 30 | 1.0000 | 1.0000 | n/a | 1.0000 | 0.5333 |
| fresh paraphrase/OOD | 30 | 0.4333 | 0.2500 | 0.1667 | 1.0000 | 0.2381 |

Interpretation: v2 is the clean candidate after official/fresh held-out leakage cleanup. It improves fresh true accuracy from 0/16 to 4/16 while preserving false/OOD 8/8, but it still over-refuses casual true questions. Do not promote it as the default demo adapter until train-only casual true paraphrases are added and re-evaluated.

Important metric caveat: `answerability_acc` is only the parsed `answerability:` field accuracy. Exact citation on answerable rows is much lower (`domain=0.2556`, `official=0.3333`, `fresh=0.2273`), and `docs/tuned_slm_failure_diagnosis.md` shows that the model mostly cites retrieved rank 1 instead of selecting among retrieved chunks.

## Run Demo

```powershell
python app/gradio_app.py
```

Modes:

- `RAG-only`
- `Base SLM + RAG`
- `Tuned SLM`
- `LLM-RAG` reserved placeholder

For tuned mode, optionally set:

```powershell
$env:TUNED_SLM_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
$env:TUNED_SLM_ADAPTER_DIR="outputs/slm_lora_random_control_blind_safe_final/checkpoint-250"
```

The tuned default is a clean development baseline. It failed the frozen
blind-opening gates, so the demo does not imply final held-out performance.

## Smoke Tests

```powershell
python -m compileall -q src app
python src/run_smoke_tests.py
```

Expected:

```json
{
  "smoke_tests": "ok"
}
```

## Final Limitations

- The frozen blind was intentionally not opened because no clean checkpoint passed every development gate.
- The selected clean step-250 baseline still under-refuses unsupported slots and wholly unsupported fresh questions.
- Base Qwen does not reliably follow the required line schema and produced substantive unsafe answers on both fresh safety rows.
- LLM-RAG has no comparable current API run; historical v1 values are reference-only.
- Additional training, retrieval variants, and prompt tuning are outside this finalized portfolio cycle.
