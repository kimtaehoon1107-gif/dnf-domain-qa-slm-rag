# Domain Retriever Missing Analysis

This note analyzes the 43 domain-expanded answerable rows where the expected gold chunk is not present in the top-20 retriever candidates.

Inputs:

- `outputs/domain_retriever_candidate_report.json`
- `data/processed/domain_eval_set_expanded.jsonl`
- `data/processed/domain_doc_chunks.jsonl`

Generated artifacts:

- `outputs/domain_retriever_missing_analysis.json`
- `outputs/domain_retriever_missing_review.csv`

## Summary

| Metric | Value |
|---|---:|
| Answerable rows in candidate report | 90 |
| Gold missing from top-20 | 43 |
| Missing rate | 0.4778 |
| Expected chunks missing from index | 0 |
| Expected parent found via sibling chunk | 8 |

The largest visible pattern is not a single reranking failure. Many misses are caused by under-specified evaluation questions that do not name the fact, entity, reward, period, or condition present in the evidence span.

## Heuristic Categories

Categories are overlapping heuristics, not mutually exclusive labels.

| Category | Count | Interpretation |
|---|---:|---|
| `generic_or_underspecified_question` | 26 | Question uses broad phrasing such as "핵심", "내용", "공지", "정보", or "관련" while barely overlapping the evidence span. |
| `low_question_evidence_overlap` | 15 | Question has very low token overlap with the evidence span and the expected parent was not retrieved. |
| `retriever_candidate_generation_miss` | 12 | No stronger heuristic fired; inspect dense/lexical candidate generation directly. |
| `sibling_parent_retrieved` | 8 | The expected parent document appears in top-20, but the expected chunk does not. This points to chunk boundary/windowing rather than pure document recall. |
| `top5_doc_type_mismatch` | 7 | Top candidates are from different document types than the expected chunk. |
| `date_or_period_query` | 1 | Date/period query where routing or metadata may matter. |

Recommended action buckets:

| Recommendation | Rows |
|---|---:|
| Rewrite eval question from the evidence fact before retrieval tuning. | 22 |
| Treat as candidate-generation miss; inspect lexical/dense query behavior. | 12 |
| Inspect chunk boundary or consider parent/window context while keeping chunk citation. | 8 |
| Inspect query routing/doc-type cues or retrieval ranking. | 1 |

## Representative Rows

| Eval ID | Question | Category | Notes |
|---|---|---|---|
| `domain_eval_0005` | `공식 공지 핵심은 뭐야?` | generic + low overlap + doc-type mismatch | The question does not identify the actual issue/fact in the notice. |
| `domain_eval_0013` | `이벤트 핵심 내용은 뭐야?` | generic + low overlap | Too broad to select the specific event card chunk. |
| `domain_eval_0010` | `입장 제한 이용 조건은 뭐야?` | sibling parent retrieved | `official_guide_1202__chunk_002` is retrieved, but expected chunk is `chunk_001`. |
| `domain_eval_0016` | `변경/수정 핵심은 뭐야?` | sibling parent + generic | Same update parent appears through sibling chunks; the question is also very broad. |
| `domain_eval_0017` | `판매 기간은 어떻게 안내돼?` | date/period + doc-type mismatch | The query is plausible, but top candidates route toward guide selling content. |

## Interpretation

Domain recall@20 is currently too low for reranking alone to fix. However, the missing rows are mixed:

1. Many rows should be repaired as evaluation data first.
   - Generic prompts such as "핵심 내용" or "공지 핵심" should be rewritten from the actual `evidence_span`.
   - These rows inflate apparent retriever failure because the query does not contain enough factual signal.

2. Some rows are chunk/window problems.
   - In 8 rows, the expected parent is present in top-20 through a sibling chunk.
   - Parent/window context can improve generation quality, but citation scoring should remain chunk-level.

3. A smaller set remains true candidate-generation failure.
   - These 12 rows are the best targets for dense/lexical query analysis, metadata prefix tests, or candidate expansion.

## Recommended Next Step

Before training RAFT v3:

1. Manually review `outputs/domain_retriever_missing_review.csv`.
2. Rewrite or remove under-specified domain eval questions.
3. Re-run candidate recall on the repaired eval set.
4. Only then decide whether domain needs retriever changes, chunk/window changes, or RAFT changes.

For official/fresh:

- Official recall@20 is already 0.8333, so reranker/rank-mode A/B is a reasonable next retrieval experiment.
- Fresh recall@10/20 is already 1.0000, so fresh failures should be treated mainly as SLM answerability/evidence-handling failures.

## Anchor-Fix A/B

`src/make_domain_expanded_data.py` was updated to address the root cause behind the weak template family:

- Normalize text to NFC before token/topic processing.
- Reject verb/connective/table-noise anchors such as `있다면`, `확인하기`, `이동하여`, `교환가능`, `닫기 이전`, `단계1 단계2`.
- Reject weak generic topics before emitting fact QA rows.
- Replace the broad `핵심 내용` / `이용 조건` templates with more specific condition, usage, event, notice, and patch phrasing.
- Expand the candidate span pool so quality filtering can keep the 80 true / 10 partial / 30 false eval shape.
- Make `--legacy-eval-set` accept multiple files by defaulting to both `official_eval_set.jsonl` and `fresh_paraphrase_eval_set.jsonl`.
- Block train questions that appear verbatim in domain eval or the legacy held-out eval sets.

A/B artifacts were generated without promoting them to canonical files:

- `outputs/domain_eval_set_expanded_anchorfix.jsonl`
- `outputs/domain_train_qa_expanded_anchorfix.jsonl`
- `outputs/domain_retriever_candidate_report_anchorfix.json`
- `outputs/domain_retriever_missing_analysis_anchorfix.json`
- `outputs/domain_retriever_missing_review_anchorfix.csv`
- `outputs/domain_dataset_validation_report_anchorfix.json`

Validation:

| Check | Value |
|---|---:|
| eval rows | 120 |
| train rows | 320 |
| train/eval parent overlap | 0 |
| train/eval chunk overlap | 0 |
| train/eval question overlap | 0 |
| train vs official/fresh parent overlap | 0 |
| train vs official/fresh question overlap | 0 |
| validation status | ok |

Retriever A/B on the same `outputs/chroma_domain_chunks` index:

| Eval | recall@3 | recall@5 | recall@10 | recall@20 | MRR@10 | missing top-20 |
|---|---:|---:|---:|---:|---:|---:|
| current canonical | 0.3444 | 0.3778 | 0.4444 | 0.5222 | 0.3024 | 43 |
| anchor-fix candidate | 0.5222 | 0.6000 | 0.6667 | 0.7889 | 0.4216 | 19 |

The old `핵심` / `이용 조건` family is gone in the candidate eval. This confirms that a large part of the previous domain recall gap was caused by generated question quality, not retriever capability.

The candidate should not be blindly promoted yet. The remaining 19 missing rows still include 8 rows tagged as generic/under-specified by the heuristic analyzer, so `outputs/domain_retriever_missing_review_anchorfix.csv` should be reviewed before canonical replacement.
