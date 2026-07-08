# Tuned-SLM Failure Diagnosis Before v3

This note diagnoses the Qwen 0.5B gate-balanced v2 adapter before starting another training round. The goal is to avoid blindly creating v3/v4/v5 without knowing which failure mode is being targeted.

## Inputs

Adapter:

- `outputs/slm_lora_qwen_domain_gate_balanced_v2`

Reports:

- `outputs/tuned_slm_qwen_domain_gate_balanced_v2_eval.json`
- `outputs/tuned_slm_qwen_domain_gate_balanced_v2_official_eval.json`
- `outputs/tuned_slm_qwen_domain_gate_balanced_v2_fresh_eval.json`
- `outputs/tuned_slm_v2_diagnostic_report.json`
- `outputs/domain_retriever_candidate_report.json`
- `outputs/official_retriever_candidate_report.json`
- `outputs/fresh_retriever_candidate_report.json`
- `outputs/raft_gold_position_report.json`

Oracle-context reports:

- span oracle:
  - `outputs/tuned_slm_qwen_domain_gate_balanced_v2_domain_oracle_eval.json`
  - `outputs/tuned_slm_qwen_domain_gate_balanced_v2_official_oracle_eval.json`
  - `outputs/tuned_slm_qwen_domain_gate_balanced_v2_fresh_oracle_eval.json`
- chunk oracle:
  - `outputs/tuned_slm_qwen_domain_gate_balanced_v2_domain_chunk_oracle_eval.json`
  - `outputs/tuned_slm_qwen_domain_gate_balanced_v2_official_chunk_oracle_eval.json`
  - `outputs/tuned_slm_qwen_domain_gate_balanced_v2_fresh_chunk_oracle_eval.json`

## Key Finding

`answerability_accuracy` alone is too optimistic. It measures only whether the generated `answerability:` field matches the expected label. It does not mean the model cited the correct evidence or answered from the correct chunk.

| Eval | answerability acc | exact citation on answerable | answerability + exact citation |
|---|---:|---:|---:|
| domain expanded | 1.0000 | 0.2556 | 0.2556 |
| official | 1.0000 | 0.3333 | 0.3333 |
| fresh paraphrase/OOD | 0.4333 | 0.2273 | 0.2273 |

Strict citation metrics now include macro precision, macro recall, and exact set match. In the current one-citation generations these match the exact-citation numbers above, but the stricter fields are needed once the model emits multiple citations.

## Rank-1 Citation Bias

The model mostly cites the first retrieved chunk, not the best evidence chunk.

| Eval | predicted citation ranks |
|---|---|
| domain expanded | `rank_1`: 90 / 90 answerable rows |
| official | `rank_1`: 24 / 24 answerable rows |
| fresh paraphrase/OOD | `rank_1`: 5 / 5 cited answerable rows |

When the gold chunk is ranked first, exact citation succeeds. When the gold chunk is rank 2 or rank 3, exact citation currently fails.

| Eval | gold rank 1 exact citation | gold rank 2 exact citation | gold rank 3 exact citation | gold missing |
|---|---:|---:|---:|---:|
| domain expanded | 23 / 23 | 0 / 6 | 0 / 3 | 58 |
| official | 8 / 8 | 0 / 5 | 0 / 2 | 9 |
| fresh paraphrase/OOD | 5 / 17 | 0 / 4 | n/a | 1 |

Interpretation: for domain/official, the model can format citations, but it is not selecting among retrieved evidence. It is behaving like a rank-1 copier.

## Retriever Candidate Recall

Retriever-only candidate recall uses one `retrieve(..., top_k=20)` call per question and slices the resulting ranked list for `@3/@5/@10/@20`.

| Eval | answerable rows | recall@3 | recall@5 | recall@10 | recall@20 | MRR@10 |
|---|---:|---:|---:|---:|---:|---:|
| domain expanded | 90 | 0.3444 | 0.3778 | 0.4444 | 0.5222 | 0.3024 |
| official | 24 | 0.6250 | 0.6667 | 0.7500 | 0.8333 | 0.3896 |
| fresh paraphrase/OOD | 22 | 0.9545 | 0.9545 | 1.0000 | 1.0000 | 0.8687 |

Interpretation:

- Domain has a candidate-generation problem: even top-20 misses 43/90 gold chunks.
- Official has enough top-20 candidates for reranking to matter, but rank 1 is weak.
- Fresh retrieval is mostly solved; the remaining failure is model-side answerability/evidence handling.

## RAFT Gold Position Check

Codex independently re-counted `data/processed/domain_raft_sample_expanded_gate_balanced.jsonl`.

| Check | Value |
|---|---:|
| rows | 456 |
| citation rows | 279 |
| answerable/partial rows | 279 |
| false rows | 177 |
| citation rows with gold at document position 1 | 279 / 279 |
| false rows with gold role | 0 |
| answerable rows without gold role | 0 |

This confirms the suspected training signal problem: every cited answerable/partial RAFT row places the gold document first.

## Oracle Context Check

`span_oracle` means the prompt receives only `evidence_span` when available. This is an easy upper bound. `chunk_oracle` means the prompt receives the full expected chunk text. False rows receive no gold evidence.

| Eval | normal answerability | span oracle answerability | chunk oracle answerability | normal exact citation | span oracle exact citation | chunk oracle exact citation |
|---|---:|---:|---:|---:|---:|---:|
| domain expanded | 1.0000 | 1.0000 | 1.0000 | 0.2556 | 1.0000 | 1.0000 |
| official | 1.0000 | 1.0000 | 1.0000 | 0.3333 | 1.0000 | 1.0000 |
| fresh paraphrase/OOD | 0.4333 | 0.6667 | 0.5667 | 0.2273 | 0.5455 | 0.4091 |

Interpretation:

- Domain/official failures are mostly retrieval ordering plus rank-1 citation copying.
- Fresh failures are mixed: removing retrieval noise helps, but full chunk context is harder than span context and still leaves many casual true and partial questions over-refused.

## Fresh Span-Oracle Failures

Even with span-oracle context, these fresh rows are still refused. Chunk oracle is harder than span oracle and should be inspected separately when selecting training examples.

- `fresh_para_0002`: "이번주 정기점검 몇시에 끝나? 2026년 7월 2일 공지 기준으로 알려줘."
- `fresh_para_0003`: "7월 2일 점검 전에 게임 꺼야 한다고 돼 있어?"
- `fresh_para_0004`: "7/2 클라 패치에서 트리니티 화면 멈춤 문제 고쳤어?"
- `fresh_para_0010`: "웨딩 아바타 풀세트 상자 삭제 시간도 문서에 있어?"
- `fresh_para_0012`: "트레이닝 시뮬레이션 들어가면 바로 115레벨 되는 거 맞아?"
- `fresh_para_0016`: "우편함 보관 기간 지나면 복구 가능해?"
- `fresh_para_0017`: partial personal decision based on maintenance time
- `fresh_para_0018`: partial personal decision based on event rewards
- `fresh_para_0021`: partial personal decision based on boost-up capsule
- `fresh_para_0022`: partial personal decision based on mail retention

This means v3 should not only add more data. It needs targeted coverage for:

- casual Korean true questions,
- yes/no questions whose answer is grounded in evidence,
- "문서에는 X까지 확인 가능하지만 개인 결정은 대신할 수 없음" partial responses.

## Diagnosis

There are two separate bottlenecks.

1. Evidence selection bottleneck:
   - The model cites retrieved rank 1 almost mechanically.
   - If gold is rank 2/3, it usually does not select it.
   - Domain/official oracle results show the model can answer correctly when gold-only context is supplied.
   - The RAFT data explains this behavior: all 279 citation rows put gold at document position 1.

2. Casual/partial answerability bottleneck:
   - Fresh true/partial questions are often refused even when retrieval finds the gold chunk.
   - Gold-only context improves fresh accuracy but does not solve it.
   - This is not only a retrieval problem.

## Do Not Do Next

Do not start a generic v3 by simply adding more RAFT rows. That would likely produce another numbered adapter without isolating the failure.

## Recommended Next Experiments

1. Candidate generation for domain:
   - Domain recall@20 is only 0.5222, so reranking alone cannot fix most domain misses.
   - Inspect missing top-20 rows for eval quality, chunking, and query formulation issues.

2. Retrieval ordering / reranker A/B for official and fresh:
   - Optimize for gold rank 1, not only hit@3/hit@5.
   - Re-run the existing v2 adapter after reranking.
   - If exact citation rises without retraining, retrieval ordering was the dominant issue.

3. Evidence-selection training redesign:
   - Randomize gold evidence position in RAFT rows.
   - Include hard negatives before the gold chunk.
   - Preserve expected citation to the non-first gold chunk.
   - Measure predicted citation rank after training.

4. Fresh paraphrase training data:
   - Add train-only casual true paraphrases similar in style to fresh, without copying fresh questions.
   - Add partial examples that answer the document-grounded part and refuse only the personal decision part.
   - Keep `fresh_paraphrase_eval_set.jsonl` held out.

5. Reporting metric change:
   - Report `answerability_acc` separately from `answerability_and_exact_citation`.
   - Report citation precision, recall, and exact set match.
   - Treat `answerability 1.0` as field compliance/labeling behavior, not full answer quality.
