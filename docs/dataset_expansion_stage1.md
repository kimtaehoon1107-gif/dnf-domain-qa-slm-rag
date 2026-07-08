# Dataset Expansion Stage 1

This stage expands the project beyond the small official-only eval/RAFT scaffold. The goal is not just to make more rows, but to preserve parent-document split discipline, exact evidence spans, refusal examples, and leakage checks.

## Scope

Inputs:

- `data/processed/official_doc_chunks.jsonl`
- `data/processed/guide_chunks.jsonl`

Outputs:

| Artifact | Rows | Purpose |
|---|---:|---|
| `data/processed/domain_doc_chunks.jsonl` | 1,307 | official + guide retrieval chunks |
| `data/processed/domain_parent_splits.json` | 188 parents | parent-doc train/dev/eval split |
| `data/processed/domain_eval_set_expanded.jsonl` | 120 | expanded held-out eval |
| `data/processed/domain_train_qa_expanded.jsonl` | 308 | train-only QA rows after fresh held-out parent/question cleanup |
| `data/processed/domain_raft_sample_expanded.jsonl` | 300 | train-only RAFT rows |
| `outputs/chroma_domain_chunks` | 1,307 | BGE-M3 combined Chroma index |
| `outputs/domain_dataset_validation_report.json` | 1 | validation report |

Parent split:

| Split | Parent docs |
|---|---:|
| train | 127 |
| dev | 22 |
| eval | 39 |

The split is by `parent_doc_id`, not chunk ID.

## Dataset Mix

Expanded eval:

| answerability | rows |
|---|---:|
| true | 80 |
| partial | 10 |
| false | 30 |

Train QA:

| answerability | rows |
|---|---:|
| true | 230 |
| partial | 19 |
| false | 59 |

RAFT:

| answerability | rows |
|---|---:|
| true | 222 |
| partial | 19 |
| false | 59 |

False rows cover prompt injection, prompt leakage, exploit requests, OOD weather, realtime price, personal account checks, unsupported prediction, unsupported rewards, personal-character decisions, and unrelated stock recommendations.

## Validation

`src/validate_domain_dataset.py` checks:

- expected chunks exist
- evidence spans appear in expected chunks
- train/eval parent overlap is zero
- train/eval chunk overlap is zero
- train/eval question overlap is zero
- RAFT contexts/citations do not include held-out eval chunks or parents
- extra held-out official/fresh eval parents do not appear in train QA or RAFT contexts
- extra held-out official/fresh eval questions do not appear in train QA or RAFT
- false rows have empty evidence/citations
- answerable rows have non-generic answers
- title-overlap warnings
- duplicate question warnings

Current report:

| Check | Result |
|---|---:|
| status | ok |
| validation errors | 0 |
| validation warnings | 0 |
| train/eval parent overlap | 0 |
| train/eval chunk overlap | 0 |
| eval expected chunks | 67 |
| train expected chunks | 191 |
| extra held-out train parent overlap | 0 |
| extra held-out RAFT context parent overlap | 0 |
| extra held-out train question overlap | 0 |
| extra held-out RAFT question overlap | 0 |

## Question Quality Review Loop

Stage 1 now includes a lightweight human-review export:

| Artifact | Rows | Purpose |
|---|---:|---|
| `outputs/domain_review_samples.csv` | 100 | spreadsheet-friendly review sample |
| `labeling/domain_review_tasks.jsonl` | 100 | JSONL review tasks for labeling workflows |

`src/make_review_samples.py` prioritizes rows with obvious quality flags, then balances by source and answerability. The current export has no automatic issue flags after removing comma-anchor questions, over-generic templates, duplicate phrasing, and footer/nickname-list spans.

## Baseline Metrics

Expanded domain retrieval uses BGE-M3 + hybrid, top-k 5.

| Eval | answerable | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|---:|
| domain expanded | 90 | 0.2556 | 0.3556 | 0.3778 | 0.3050 |

Answer evaluation:

| rows | answerability acc | citation hit | answerable citation hit | answer relevance | atomic fact support | unsupported rows |
|---:|---:|---:|---:|---:|---:|---:|
| 120 | 1.0000 | 0.4417 | 0.2556 | 0.5142 | 1.0000 | 0 |

Interpretation: the expanded eval is much harder than the 30-row official eval because it mixes guide and official documents, includes partial/refusal rows, and uses more diverse fact spans. The question-quality pass reduced title/anchor artifacts; hit@5 is lower than the first expanded draft, while hit@1, answer relevance, and answerable citation hit improved. This is a more honest baseline for later reranker or SLM comparisons.

## LoRA Readiness

Dry-run on expanded RAFT:

| Check | Value |
|---|---:|
| rows | 300 |
| true / partial / false | 222 / 19 / 59 |
| avg training text chars | 1520.54 |
| max training text chars | 2768 |
| loss masking | completion-only after `### Answer` |

## Reproduction

```powershell
python src/make_domain_expanded_data.py
python src/make_raft_dataset.py --docs data/processed/domain_doc_chunks.jsonl --qa data/processed/domain_train_qa_expanded.jsonl --exclude-eval-set data/processed/domain_eval_set_expanded.jsonl data/processed/official_eval_set.jsonl data/processed/fresh_paraphrase_eval_set.jsonl --output data/processed/domain_raft_sample_expanded.jsonl --max-rows 300 --distractors 2
python src/validate_domain_dataset.py --chunks data/processed/domain_doc_chunks.jsonl --eval-set data/processed/domain_eval_set_expanded.jsonl --train-qa data/processed/domain_train_qa_expanded.jsonl --raft data/processed/domain_raft_sample_expanded.jsonl --output outputs/domain_dataset_validation_report.json
python src/build_index.py --docs data/processed/domain_doc_chunks.jsonl --persist-dir outputs/chroma_domain_chunks --model-name BAAI/bge-m3 --reset
python src/evaluate.py --eval-set data/processed/domain_eval_set_expanded.jsonl --persist-dir outputs/chroma_domain_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/domain_eval_retrieval_report.json
python src/evaluate_answers.py --eval-set data/processed/domain_eval_set_expanded.jsonl --persist-dir outputs/chroma_domain_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/domain_answer_eval_report.json
python src/make_review_samples.py --chunks data/processed/domain_doc_chunks.jsonl --eval-set data/processed/domain_eval_set_expanded.jsonl --raft data/processed/domain_raft_sample_expanded.jsonl --limit 100 --csv-output outputs/domain_review_samples.csv --jsonl-output labeling/domain_review_tasks.jsonl
python src/finetune_lora.py --train-file data/processed/domain_raft_sample_expanded.jsonl --output-dir outputs/slm_lora_domain --dry-run
```
