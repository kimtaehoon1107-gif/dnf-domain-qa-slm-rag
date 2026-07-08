# RAG-only vs LLM-RAG vs Tuned-SLM Comparison

This report separates three things that should not be mixed:

- `RAG-only`: the current v2 MVP, using Chroma/Sentence-Transformers retrieval and a rule-based grounded answer.
- `LLM-RAG`: the v1 `dnf-llm-eval` baseline results.
- `Tuned-SLM`: the v2 target path. The current LoRA/Qwen runs now include expanded, official, and fresh paraphrase/OOD comparisons, but still need train-only casual paraphrase data before production-style quality claims.

## Evaluation Axes

| Axis | Metric | Purpose |
|---|---|---|
| Retrieval | `hit_rate@k`, MRR | Whether any expected evidence ID appears in top-k. |
| Chunk retrieval | `expected_chunk_ids` hit | Whether the exact gold chunk is retrieved. |
| Answerability | accuracy | Whether unsupported/OOD/safety questions are refused. |
| Citation | hit, precision, recall | Whether cited evidence matches expected evidence. |
| Faithfulness | atomic fact support | Whether answer facts are supported by retrieved evidence. |
| Relevance | context/answer relevance | Lightweight triage without external judge APIs. |

## Current RAG-only Results

Retrieval command:

```powershell
python src/evaluate.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_report.json
```

| Eval set | match scope | answerable | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|---:|
| synthetic eval | parent doc | 28 | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| official fact eval | chunk | 24 | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| domain expanded eval | chunk | 90 | 0.2556 | 0.3556 | 0.3778 | 0.3050 |

The official result is intentionally harder than the previous title-derived eval. It uses body fact questions, `gold_answer`, `evidence_span`, and `expected_chunk_ids`. The current RAG-only baseline uses promoted header-clean fixed 1200-char official chunks, BGE-M3 embeddings, and hybrid ranking.

Header-clean/RRF A/B is tracked separately in `docs/header_clean_rrf_ablation.md`. The no-header + hybrid variant improved hit@1/MRR and answerable citation hit; its hit@5 drop was traced to one top-5 boundary row, so it was promoted to canonical. RRF is retained only as a baseline because it lowered retrieval recall on the official eval.

Answer evaluation:

| Eval set | rows | answerability acc | citation hit | citation precision | citation recall | answer relevance | atomic fact support |
|---|---:|---:|---:|---:|---:|---:|---:|
| synthetic | 30 | 1.0000 | 0.9667 | 0.9667 | 0.9667 | 0.8078 | 1.0000 |
| official fact eval | 30 | 1.0000 | 0.4667 | 0.4667 | 0.4667 | 0.4106 | 1.0000 |
| domain expanded eval | 120 | 1.0000 | 0.4417 | 0.4417 | 0.4417 | 0.5142 | 1.0000 |

Interpretation: BGE-M3 + hybrid improves retrieval and citation metrics, and the rule gate now handles unsupported/OOD/safety rows. hit@1 and exact citation quality remain the next bottleneck. This is useful for portfolio credibility because the metric no longer hides behind title overlap.

## v1 LLM-RAG Baseline

Baseline repo: `dnf-llm-eval`, checked at commit `ae97ef95936995cbe4d5f684bb09d49b4847832d`.

| System | document-QA avg | overall avg | OOD avg |
|---|---:|---:|---:|
| Non-RAG baseline | 11.27 / 21 | 13.87 / 21 | 21.00 / 21 |
| RAG applied | 18.86 / 21 | 19.43 / 21 | 21.00 / 21 |

v1 proves that retrieval improves DNF document QA. v2 now focuses on better data construction, answerability labeling, chunk-level evidence, RAFT training data, and reproducible SLM fine-tuning.

## Tuned-SLM Status

Implemented:

- RAFT samples with gold and distractor evidence.
- Official RAFT regenerated from `official_train_qa.jsonl`, excluding held-out eval parent docs/chunks and including refusal examples.
- Expanded domain RAFT generated from official + guide train parents after extra held-out cleanup: 300 rows, `true=222`, `partial=19`, `false=59`.
- Gate-balanced RAFT variant generated for SLM answerability training: 456 rows, `true=222`, `partial=57`, `false=177`.
- Expanded domain eval/RAFT review export generated: `outputs/domain_review_samples.csv`, `labeling/domain_review_tasks.jsonl`.
- Shared prompt builder in `src/prompt_format.py`.
- Completion-only masking in `src/finetune_lora.py`; loss is applied after `### Answer`.
- Tuned-SLM inference path in `src/run_tuned_slm_smoke.py`.
- Gradio mode switch for `RAG-only`, `Tuned SLM`, and reserved `LLM-RAG`.
- Qwen 0.5B LoRA Stage 1 trained on the 300-row expanded RAFT set.
- Qwen 0.5B gate-balanced LoRA trained on the earlier 460-row RAFT variant and evaluated on the 120-row expanded eval set.
- Qwen 0.5B gate-balanced v2 LoRA trained on the fresh-clean 456-row RAFT variant and evaluated on expanded, official, and fresh eval sets.

Verified smoke:

| Smoke | Result |
|---|---|
| LoRA dry-run | 41 official RAFT rows, `true=37`, `false=4`, completion-only masking reported |
| Expanded RAFT dry-run | 300 domain RAFT rows, `true=222`, `partial=19`, `false=59`, completion-only masking reported |
| tiny GPT-2 LoRA train | 2 rows trained, adapter saved |
| tiny adapter inference | adapter loaded and generated 1 row |
| Qwen 0.5B LoRA | previous 1-row CPU smoke verified training path |
| Qwen 0.5B domain LoRA | 300 rows trained on GPU, 1 epoch, train loss 0.1276, adapter saved to `outputs/slm_lora_qwen_domain` |
| Qwen 0.5B cite-first LoRA | 300 rows trained on GPU, field compliance fixed, but all rows parsed as `answerability=true` |
| Qwen 0.5B gate-balanced LoRA | earlier 460-row run trained on GPU, answerability 120/120 on expanded eval, adapter saved to `outputs/slm_lora_qwen_domain_gate_balanced` |
| Qwen 0.5B gate-balanced v2 LoRA | 456 fresh-clean rows trained on GPU, 1 epoch, train loss 0.0531, adapter saved to `outputs/slm_lora_qwen_domain_gate_balanced_v2` |

The 300-row Qwen LoRA run proved the local training path. The cite-first pass fixed `answerability/citations/answer` field compliance but exposed a structured refusal failure: it parsed every eval row as `answerability=true`. The gate-balanced pass corrected this on the current expanded eval.

## Tuned-SLM Expanded Eval

Command:

```powershell
python src/run_tuned_slm_smoke.py --model-name Qwen/Qwen2.5-0.5B-Instruct --adapter-dir outputs/slm_lora_qwen_domain_gate_balanced --eval-set data/processed/domain_eval_set_expanded.jsonl --persist-dir outputs/chroma_domain_chunks --embedding-model-name BAAI/bge-m3 --rank-mode hybrid --output outputs/tuned_slm_qwen_domain_gate_balanced_eval.json --limit 120 --top-k 3 --max-doc-chars 500 --max-new-tokens 160 --fp16
```

| System | rows | answerability acc | true acc | partial acc | false acc | field compliance | citation hit when retrieval hit | citation in retrieved | avg answer chars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAG-only rule gate | 120 | 1.0000 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| cite-first Qwen LoRA | 120 | 0.6667 | 1.0000 | 0.0000 | 0.0000 | 1.0000 | 0.7188 | 1.0000 | 147.4 |
| gate-balanced Qwen LoRA | 120 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7188 | 1.0000 | 134.1 |
| gate-balanced v2 Qwen LoRA | 120 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7188 | 1.0000 | 133.7 |

Interpretation: cite-first formatting solved citation-field truncation, but not answerability. Oversampling false/partial rows and strengthening the instruction taught the model to leave citations empty for unsupported questions on this eval. The v2 adapter preserves this in-distribution behavior after official/fresh held-out leakage cleanup. This is still template-distribution performance, with one important caveat: train loss remains very low.

## Tuned-SLM Official Eval

| System | rows | answerability acc | true acc | false acc | parsed chunk citation rate | citation hit when retrieval hit | avg answer chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| gate-balanced v2 Qwen LoRA | 30 | 1.0000 | 1.0000 | 1.0000 | 0.8000 | 0.5333 | 163.5 |

## Tuned-SLM Failure Diagnosis

See `docs/tuned_slm_failure_diagnosis.md` for the v2 pre-v3 diagnosis. The short version: `answerability_acc` is not full answer quality. Exact citation on answerable rows is much lower:

| Eval | answerability acc | exact citation on answerable | answerability + exact citation |
|---|---:|---:|---:|
| domain expanded | 1.0000 | 0.2556 | 0.2556 |
| official | 1.0000 | 0.3333 | 0.3333 |
| fresh paraphrase/OOD | 0.4333 | 0.2273 | 0.2273 |

Chunk-oracle context recovers domain/official exact citation to 1.0000, which points to retrieval ordering and rank-1 citation copying as the main problem there. Fresh chunk oracle improves over normal retrieval but remains weak, so casual true and partial answerability need targeted train-only coverage. Retriever-only top20 analysis also shows that domain has a candidate-generation problem: recall@20 is only 0.5222.

## Fresh Paraphrase/OOD Eval

Fresh eval file: `data/processed/fresh_paraphrase_eval_set.jsonl`

This hand-written slice tests casual true questions, partial personal-decision questions, and OOD/safety false questions. It is intentionally not used for RAFT training.

| Eval | rows | true | partial | false | retrieval hit@1 | retrieval hit@3 | retrieval hit@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| fresh paraphrase/OOD | 30 | 16 | 6 | 8 | 0.7727 | 0.9545 | 0.9545 |

| System | rows | answerability acc | true acc | partial acc | false acc | citation hit when retrieval hit | avg answer chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| RAG-only answer evaluator | 30 | 0.7000 | n/a | n/a | n/a | n/a | n/a |
| gate-balanced Qwen LoRA | 30 | 0.3000 | 0.0000 | 0.1667 | 1.0000 | 0.0476 | 43.0 |
| gate-balanced v2 Qwen LoRA | 30 | 0.4333 | 0.2500 | 0.1667 | 1.0000 | 0.2381 | 60.3 |

Interpretation: retrieval finds the expected chunk for 21/22 answerable-or-partial rows at top-3, but the tuned SLM over-refuses casual true questions. The fresh-clean v2 adapter improves true accuracy from 0/16 to 4/16 while preserving false/OOD 8/8, but it is still not robust enough to present as a general user-facing model.

Data caveat: `outputs/slm_lora_qwen_domain_gate_balanced` predates fresh-exclusion cleanup and is retained only as a failure-analysis baseline. `outputs/slm_lora_qwen_domain_gate_balanced_v2` is the current clean candidate.

## Next Benchmark Gate

Before claiming tuned-SLM quality:

1. Review 50-100 expanded eval/RAFT rows from `outputs/domain_review_samples.csv`.
2. Add casual true paraphrases to RAFT without leaking `fresh_paraphrase_eval_set.jsonl`.
3. Rebalance SLM training to reduce over-refusal while preserving false/OOD refusal.
4. Improve retrieval/reranking only after the fresh answerability failure is addressed.
5. Compare `RAG-only`, `LLM-RAG`, and `Tuned-SLM` in Gradio with the same held-out eval assumptions.
