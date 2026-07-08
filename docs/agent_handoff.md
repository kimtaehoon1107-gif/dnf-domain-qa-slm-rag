# Agent Handoff - DNF Domain QA SLM/RAG

> Overwrite this file at handoff time. Keep the full history in `docs/project_progress_report.md` and durable project rules in `AGENTS.md`.

## Current Goal

Do not start another generic v3 training run yet. First close the diagnostic loop around retrieval candidates, RAFT evidence-position bias, oracle behavior, and citation metrics so the next experiment targets a known failure mode.

## Current State

- Latest adapter: `outputs/slm_lora_qwen_domain_gate_balanced_v2`
- Latest RAFT file: `data/processed/domain_raft_sample_expanded_gate_balanced.jsonl` (456 rows)
- `answerability_accuracy=1.0` on domain/official is known to be over-optimistic.
- Exact citation is much lower:
  - domain expanded: 0.2556
  - official: 0.3333
  - fresh paraphrase/OOD: 0.2273
- Strict citation metrics have been added in `src/analyze_tuned_slm_diagnostics.py`:
  - precision macro
  - recall macro
  - exact set match
- Retriever-only top-20 diagnostics are complete:
  - domain: recall@3 0.3444, recall@5 0.3778, recall@10 0.4444, recall@20 0.5222, MRR@10 0.3024
  - official: recall@3 0.6250, recall@5 0.6667, recall@10 0.7500, recall@20 0.8333, MRR@10 0.3896
  - fresh: recall@3 0.9545, recall@5 0.9545, recall@10 1.0000, recall@20 1.0000, MRR@10 0.8687
- RAFT gold position was independently re-counted:
  - citation rows: 279
  - answerable-or-partial rows: 279
  - citation rows with gold document at position 1: 279 / 279
  - false rows with gold role: 0
- Oracle mode split is complete:
  - `span_oracle`: evidence span only
  - `chunk_oracle`: full expected chunk
  - domain/official chunk oracle exact citation: 1.0000
  - fresh chunk oracle answerability: 0.5667, exact citation: 0.4091

## Completed In Latest Turn

Added domain top-20 missing analysis:

- Script: `src/analyze_domain_missing_retrieval.py`
- JSON output: `outputs/domain_retriever_missing_analysis.json`
- CSV review sheet: `outputs/domain_retriever_missing_review.csv`
- Diagnosis note: `docs/domain_retriever_missing_analysis.md`

Result:

- Domain answerable rows: 90
- Gold missing from top-20: 43
- Missing rate: 0.4778
- Expected chunks missing from index: 0
- Expected parent retrieved through sibling chunk: 8

Overlapping heuristic categories:

- `generic_or_underspecified_question`: 26
- `low_question_evidence_overlap`: 15
- `retriever_candidate_generation_miss`: 12
- `sibling_parent_retrieved`: 8
- `top5_doc_type_mismatch`: 7
- `date_or_period_query`: 1

Interpretation:

- Domain recall@20 is not just a reranking problem.
- Many domain eval questions are too generic, e.g. "공식 공지 핵심은 뭐야?", "이벤트 핵심 내용은 뭐야?"
- Some misses are chunk/window issues where the same parent document is retrieved via a sibling chunk.
- Only the remaining candidate-generation misses should be used to justify retrieval changes.

Then implemented an anchor-fix candidate in `src/make_domain_expanded_data.py`:

- NFC normalization before topic/token handling.
- Reject verb/connective/table-noise anchors such as `있다면`, `확인하기`, `이동하여`, `교환가능`, `닫기 이전`, `단계1 단계2`.
- Replace the broad `핵심 내용` / `이용 조건` template family with more specific condition, usage, event, notice, and patch phrasing.
- Expand candidate spans so filtering can still produce 80 true / 10 partial / 30 false eval rows.
- `--legacy-eval-set` now accepts multiple files and defaults to both `official_eval_set.jsonl` and `fresh_paraphrase_eval_set.jsonl`.
- Domain train generation now blocks verbatim questions from domain eval plus official/fresh held-out evals.

Anchor-fix artifacts were generated as A/B outputs, not promoted to canonical files:

- `outputs/domain_eval_set_expanded_anchorfix.jsonl`
- `outputs/domain_train_qa_expanded_anchorfix.jsonl`
- `outputs/domain_retriever_candidate_report_anchorfix.json`
- `outputs/domain_retriever_missing_analysis_anchorfix.json`
- `outputs/domain_retriever_missing_review_anchorfix.csv`
- `outputs/domain_dataset_validation_report_anchorfix.json`

Anchor-fix validation:

- eval rows 120; train rows 320
- train/eval parent overlap 0
- train/eval chunk overlap 0
- train/eval question overlap 0
- train vs official/fresh parent overlap 0
- train vs official/fresh question overlap 0
- validation status ok

Anchor-fix retrieval A/B on the same `outputs/chroma_domain_chunks` index:

| Eval | recall@3 | recall@5 | recall@10 | recall@20 | MRR@10 | missing top-20 |
|---|---:|---:|---:|---:|---:|---:|
| current canonical | 0.3444 | 0.3778 | 0.4444 | 0.5222 | 0.3024 | 43 |
| anchor-fix candidate | 0.5222 | 0.6000 | 0.6667 | 0.7889 | 0.4216 | 19 |

The candidate eval has 0 rows containing the old `핵심` / `이용 조건` template family. However, it still has residual weak rows, and the missing analyzer still tags 8 of the 19 top-20 misses as generic/under-specified. Do not promote blindly.

## Important Caveat

The missing-row categories are heuristics, not final labels. Review `outputs/domain_retriever_missing_review.csv` before editing eval data or changing retriever behavior.

For the anchor-fix candidate, review `outputs/domain_retriever_missing_review_anchorfix.csv` before canonical promotion.

## Claude Independent Check — the 12 "clean" candidate-generation misses are not clean

Claude inspected all 12 rows tagged only `retriever_candidate_generation_miss` (no other category). **All 12 contain a generic term** (`핵심`/`이용 조건`) and follow the exact same "{anchor} 핵심 내용은 뭐야?" template as the 26 rows already tagged `generic_or_underspecified_question`. They only escaped that tag because `question_span_overlap` happened to land at/just above the 0.25 cutoff (9 of 12 sit exactly at 0.2500). Several anchors are not real topics at all: `있다면`, `확인하기`, `이동하여`, `교환가능` — verb/connective fragments, not nouns, from the anchor-extraction logic in `make_domain_expanded_data.py`.

Implication: the true count of genuine, no-confound retrieval failures in domain is likely far below 12 — possibly near zero. Most or all of the domain recall@20 gap (43/90) traces back to the eval question **generation template**, not retrieval/reranking. Row-by-row CSV edits will not fix this; the anchor-extraction logic in `make_domain_expanded_data.py` (the "핵심 내용" / "이용 조건" template family) needs to filter out non-noun anchors before regenerating domain eval questions.

## Claude Review Context

Claude previously agreed with the diagnostic-first direction:

- Do not trust `answerability_accuracy=1.0` as answer quality.
- Candidate recall and MRR@10 should be measured before retraining.
- RAFT gold position 279/279 at document position 1 explains rank-1 citation copying.
- Oracle mode should distinguish span oracle and chunk oracle.

One extra caveat from review:

- `hybrid` retrieval may slightly vary between separate `top_k=3` calls and one `top_k=20` call sliced to top 3 because candidate pools can differ. For diagnostic reports, keep using one top-20 pass and slice it consistently.

## Do Not Do

- Do not start v3 training immediately.
- Do not put `fresh_paraphrase_eval_set.jsonl` into training data.
- Do not describe `answerability_accuracy=1.0` as full answer quality.
- Do not tune domain reranking before deciding which missing rows are eval-quality problems.

## Next Actions

1. Review the anchor-fix candidate before canonical promotion.
   - Main file: `outputs/domain_retriever_missing_review_anchorfix.csv`
   - Decide whether the remaining 19 top-20 misses are acceptable, need another generator pass, or should be manually excluded from eval.
   - If accepted, promote the anchor-fix eval/train files to `data/processed/` with backups and treat old v2 eval metrics as historical.

2. If promoted, re-run domain retriever candidate recall on canonical files.
   - Use `src/evaluate_retriever_candidates.py`.
   - Keep a single top-20 retrieval pass and slice to @3/@5/@10/@20.

3. Run official reranker/rank-mode A/B only after domain eval repair is acknowledged.
   - Official recall@20 is 0.8333, so reranking can matter there.
   - Fresh recall@10/20 is already 1.0000, so fresh is mainly a model-side answerability/evidence-handling problem.

4. Design RAFT v3, but do not train until the retrieval/eval decision is clear.
   - Randomize gold evidence position.
   - Add hard negatives before gold.
   - Include non-first gold citation supervision.
   - Add train-only casual true/partial paraphrases.
   - Keep fresh eval held out.

5. Keep reporting metrics separated.
   - answerability accuracy
   - exact citation
   - citation precision/recall/exact-set-match
   - answerability plus exact citation

## Latest Verification

Commands run successfully:

- `python src/analyze_domain_missing_retrieval.py --candidate-report outputs/domain_retriever_candidate_report.json --eval-set data/processed/domain_eval_set_expanded.jsonl --chunks data/processed/domain_doc_chunks.jsonl --json-output outputs/domain_retriever_missing_analysis.json --csv-output outputs/domain_retriever_missing_review.csv`
- `python src/make_domain_expanded_data.py --combined-output outputs/domain_doc_chunks_anchorfix.jsonl --split-output outputs/domain_parent_splits_anchorfix.json --eval-output outputs/domain_eval_set_expanded_anchorfix.jsonl --train-output outputs/domain_train_qa_expanded_anchorfix.jsonl`
- `python src/validate_domain_dataset.py --chunks outputs/domain_doc_chunks_anchorfix.jsonl --eval-set outputs/domain_eval_set_expanded_anchorfix.jsonl --train-qa outputs/domain_train_qa_expanded_anchorfix.jsonl --raft outputs/nonexistent_anchorfix_raft.jsonl --output outputs/domain_dataset_validation_report_anchorfix.json`
- `python src/evaluate_retriever_candidates.py --eval-set outputs/domain_eval_set_expanded_anchorfix.jsonl --persist-dir outputs/chroma_domain_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --cutoffs 3,5,10,20 --output outputs/domain_retriever_candidate_report_anchorfix.json`
- `python src/analyze_domain_missing_retrieval.py --candidate-report outputs/domain_retriever_candidate_report_anchorfix.json --eval-set outputs/domain_eval_set_expanded_anchorfix.jsonl --chunks outputs/domain_doc_chunks_anchorfix.jsonl --json-output outputs/domain_retriever_missing_analysis_anchorfix.json --csv-output outputs/domain_retriever_missing_review_anchorfix.csv`
- `python -m compileall src app`
- `python src/run_smoke_tests.py`
