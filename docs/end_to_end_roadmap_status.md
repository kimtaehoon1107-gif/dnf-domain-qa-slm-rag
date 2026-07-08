# End-to-End Roadmap Status

This document maps the handoff roadmap to the current repository state.

## Summary

| # | Roadmap item | Status | Evidence |
|---:|---|---|---|
| 1 | Declare existing `dnf-llm-eval` as v1 baseline | Done | `README.md`, `docs/v1_baseline_failure_analysis.md` |
| 2 | Analyze previous failure types | Done | `docs/v1_baseline_failure_analysis.md` |
| 3 | Use Label Studio for intent, answerability, evidence quality | Config/export ready | `labeling/`, `src/label_studio_io.py` |
| 4 | Build RAFT-style data with evidence and distractors | Done, expanded | `data/processed/official_raft_sample.jsonl`, `data/processed/domain_raft_sample_expanded.jsonl` |
| 5 | Fine-tune a small model with LoRA/QLoRA | Done, first candidate | `src/finetune_lora.py`, `outputs/slm_lora_qwen_domain_gate_balanced` |
| 6 | Compare RAG, LLM-RAG, tuned SLM | Partially done | RAG-only current metrics + v1 LLM-RAG baseline + tuned-SLM expanded eval |
| 7 | Evaluate with RAGAS/FActScore-style metrics | Done as lightweight evaluator | `src/evaluate_answers.py` |
| 8 | Provide Gradio demo | Done | `app/gradio_app.py` |

## Quality Improvement Pass

Completed in this pass:

- Replaced title-derived official eval with body-fact questions.
- Added `gold_answer`, `evidence_span`, `expected_doc_id`, `expected_chunk_id`, and `expected_chunk_ids`.
- Changed retrieval evaluation wording from `recall@k` to `hit_rate@k`.
- Added chunk-level matching when `expected_chunk_ids` exist.
- Added 6 safety/OOD rows inspired by v1 adversarial/OOD sets.
- Generated `official_train_qa.jsonl` from non-held-out parent documents plus train-only safety/OOD refusal rows.
- Regenerated official RAFT from train-only rows, including refusal examples.
- Verified no held-out parent/chunk leakage into official RAFT.
- Unified SLM train/inference prompt format.
- Added completion-only masking after `### Answer`.
- Added Gradio mode selection for RAG-only, tuned-SLM, and reserved LLM-RAG.
- Rebuilt canonical retrieval indexes with BGE-M3.
- Added retrieval rank modes: `lexical_first`, `semantic`, `hybrid`, and `rrf`.
- Ran MiniLM vs BGE-M3 retrieval A/B on synthetic and official eval sets.
- Ran official chunking A/B for fixed-window and section-aware variants.
- Promoted fixed 1200-char official chunks to the canonical eval/train/RAFT/index path.
- Added explicit answerability gates for prompt-injection, exploit, OOD, realtime, and personal-account questions.
- Added a no-header official chunking A/B variant and RRF ranking baseline.
- Promoted `no-header + hybrid` to the canonical official chunk/index/eval/train/RAFT path after row-level analysis showed the hit@5 drop was one boundary case.
- Added Dataset Expansion Stage 1 with parent-doc splits, official+guide chunks, 120-row eval, 308-row train QA, and 300-row RAFT after extra held-out cleanup.
- Added expanded eval/RAFT question-quality cleanup and 100-row human-review exports.
- Trained Qwen 0.5B LoRA Stage 1 on the 300-row expanded RAFT set using local CUDA.
- Fixed tuned-SLM inference prompts to use chunk IDs instead of parent IDs for retrieved evidence.
- Added cite-first SLM output format and parser metrics for answerability/citation/answer fields.
- Found and documented the cite-first failure where all rows parsed as `answerability=true`.
- Added a gate-balanced RAFT variant and trained a Qwen 0.5B LoRA candidate that reaches 120/120 answerability on the expanded eval.

## Current Verified Metrics

Retrieval:

| Eval set | match scope | answerable | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|---:|
| synthetic | parent doc | 28 | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| official fact eval | chunk | 24 | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| domain expanded eval | chunk | 90 | 0.2556 | 0.3556 | 0.3778 | 0.3050 |

Historical fixed-1200 remap A/B result before canonical regeneration:

| Variant | match scope | answerable | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|---:|
| official fixed 1200 | chunk | 24 | 0.3333 | 0.6667 | 0.7500 | 0.4889 |

Header-clean/RRF A/B:

| Variant | rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| pre-promotion fixed 1200 | hybrid | 0.2917 | 0.6250 | 0.7083 | 0.4472 |
| pre-promotion fixed 1200 | rrf | 0.2083 | 0.4583 | 0.5000 | 0.3368 |
| promoted no-header fixed 1200 | hybrid | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| no-header fixed 1200 | rrf | 0.3333 | 0.4583 | 0.5833 | 0.4090 |

Answer evaluation:

| Eval set | rows | answerability acc | citation hit | citation recall | atomic fact support |
|---|---:|---:|---:|---:|---:|
| synthetic | 30 | 1.0000 | 0.9667 | 0.9667 | 1.0000 |
| official fact eval | 30 | 1.0000 | 0.4667 | 0.4667 | 1.0000 |
| domain expanded eval | 120 | 1.0000 | 0.4417 | 0.4417 | 1.0000 |

SLM path:

| Check | Result |
|---|---|
| LoRA dry-run | 41 official RAFT rows, `true=37`, `false=4`, completion-only masking |
| expanded RAFT dry-run | 300 domain RAFT rows, `true=222`, `partial=19`, `false=59`, completion-only masking |
| gate-balanced RAFT dry-run | 456 domain RAFT rows, `true=222`, `partial=57`, `false=177`, completion-only masking |
| tiny LoRA training smoke | 2 rows trained |
| tiny tuned-SLM inference smoke | adapter loaded and generated 1 row |
| Qwen 0.5B domain LoRA | 300 rows trained, 1 epoch, train loss 0.1276, adapter saved to `outputs/slm_lora_qwen_domain` |
| Qwen 0.5B cite-first LoRA | 300 rows trained, field compliance 1.0, but answerability collapsed to all true |
| Qwen 0.5B gate-balanced LoRA | earlier 460-row run trained, 1 epoch, answerability 120/120, adapter saved to `outputs/slm_lora_qwen_domain_gate_balanced` |
| Qwen 0.5B gate-balanced v2 LoRA | 456 fresh-clean rows trained, 1 epoch, answerability 120/120 on expanded eval, adapter saved to `outputs/slm_lora_qwen_domain_gate_balanced_v2` |

Tuned-SLM expanded eval:

| Adapter | rows | answerability acc | citation hit when retrieval hit | citation in retrieved | avg answer chars |
|---|---:|---:|---:|---:|---:|
| `outputs/slm_lora_qwen_domain_citefirst` | 120 | 0.6667 | 0.7188 | 1.0000 | 147.4 |
| `outputs/slm_lora_qwen_domain_gate_balanced` | 120 | 1.0000 | 0.7188 | 1.0000 | 134.1 |
| `outputs/slm_lora_qwen_domain_gate_balanced_v2` | 120 | 1.0000 | 0.7188 | 1.0000 | 133.7 |

Fresh paraphrase/OOD eval:

| Eval | rows | true | partial | false | retrieval hit@3 | tuned-SLM answerability acc |
|---|---:|---:|---:|---:|---:|---:|
| `data/processed/fresh_paraphrase_eval_set.jsonl` with historical gate-balanced | 30 | 16 | 6 | 8 | 0.9545 | 0.3000 |
| `data/processed/fresh_paraphrase_eval_set.jsonl` with gate-balanced v2 | 30 | 16 | 6 | 8 | 0.9545 | 0.4333 |

## Remaining Work

The project is structurally complete for portfolio demonstration, but the next real quality work is clear:

1. Human-review `outputs/domain_review_samples.csv` and apply worthwhile manual rewrites.
2. Add train-only casual true paraphrases without leaking `fresh_paraphrase_eval_set.jsonl`.
3. Rebalance SLM training to reduce over-refusal while preserving false/OOD refusal.
4. Run BGE reranker A/B only after the fresh answerability failure is addressed.

RRF remains an ablation baseline, not the current promotion candidate. The next SLM quality gate is reducing fresh true-question over-refusal.
