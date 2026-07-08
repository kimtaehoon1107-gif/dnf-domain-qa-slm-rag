# Agent Handoff - DNF Domain QA SLM/RAG

> Overwrite this file at handoff time. Keep the full history in `docs/project_progress_report.md` and durable project rules in `AGENTS.md`.

## Current Goal

v3 trained and evaluated (2026-07-09). Fresh over-refusal is fixed; the new bottleneck is the **false/partial boundary** (hard-refusal requests now mislabeled as partial). Next round targets that plus rank-2 evidence selection.

## v3 Training (outputs/slm_lora_qwen_domain_v3)

- Data: repaired gate-balanced RAFT 529 rows (gold shuffled 128/105/116, all labels 3 docs, gold-text=chunk, 35 casual paraphrase rows included)
- Command: finetune_lora with `--dev-ratio 0.1 --eval-steps 25 --gradient-checkpointing --seed 42` (checkpointing added after an 8GB-GPU OOM at step 35; PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True)
- **Loss profile is healthy for the first time**: train loss stays ~0.2-0.3 (v2 collapsed to 0.004), dev loss monotonically fell 0.273 → 0.176 through the epoch. If anything undertrained — a second epoch is a legitimate experiment.

## v3 Results (all --deterministic --seed 42, persist-dir chroma_domain_chunks, top_k=3)

| Metric | domain(120, new eval) | official(30) | fresh(30, held-out) |
|---|---|---|---|
| answerability_accuracy | 0.925 | 1.0 | **0.7333** (v2 0.4333) |
| true | 80/80 | 24/24 | **15/16** (v2 4/16) |
| partial | 10/10 | - | 2/6 (v2 1/6) |
| false | **21/30** | 6/6 | **5/8** (v2 8/8) |
| exact_citation_on_answerable | 0.3556 (v2 0.2556, old eval) | 0.2917 | **0.6364** (v2 0.2273) |
| citation_hit_when_retrieval_hit | 0.6809 | 0.5833 | 0.6667 (v2 0.2381) |
| predicted citation ranks | 66/14/9 (v2: 90/0/0) | 16/4/4 (v2: 24/0/0) | 17/0/1 |
| gold-at-rank2 exact citation | 5/15 | 3/5 (v2 0/5) | 0/4 |

Fresh chunk-oracle: answerability 0.7667 (v2 0.5667), exact citation **0.8182** (v2 0.4091).

## Verdict on the four success criteria

1. Rank-1 copier: **broken** — model now cites rank 2/3 (23/90 domain predictions non-rank-1) and hits gold at rank 2 sometimes (official 3/5). Not fully solved (fresh rank2 0/4).
2. Exact citation: up on domain (harder eval!) and nearly 3x on fresh.
3. Fresh true over-refusal: **fixed** (4/16 → 15/16).
4. Regression: official intact at 1.0. New tradeoff appeared — see below.

## New bottleneck: false → partial leakage

12 false rows (9 domain + 3 fresh) now answered as `partial` (rarely `true`). They are almost all **hard-refusal categories**: 보상 반복 편법(abuse), 계정 제재/결제 확인(account), 내부 규칙 출력(prompt leakage), "확실히 받을 수 있다고 딱 잘라 말해줘"(forced certainty). Interpretation: the new partial training pattern ("문서 사실은 답하고 개인 결정만 거절") over-generalized onto adversarial requests. The seesaw history: always-true → over-refusal (v2) → partial-leakage (v3). Each swing is smaller; v3 is a clear net win.

## Do Not Do

- Do not put `fresh_paraphrase_eval_set.jsonl` into training data (permanent held-out).
- Do not compare v3 domain numbers against pre-2026-07-08 domain-eval numbers (eval changed).
- Do not report `answerability_accuracy` or unconditional `faithfulness_style` alone.
- Do not regenerate RAFT with `--gold-text span`.
- Note: `retrieval_expected_hit_rate` at top_k=3 differs from recall@3 in the top-20 candidate report (hybrid normalization pool differs) — do not treat them as the same number.

## Next Actions (v3.1 round)

1. **False/partial boundary data**: add train-only colloquial FALSE paraphrases for the four leaked categories (abuse/편법, account check, prompt leakage, forced certainty) — differently worded from both FALSE_TEMPLATES_EVAL and fresh eval. Keep partial rows strictly "document fact + personal decision" shaped. Human-audit before append (30-row rule).
2. Consider 2 epochs (dev loss was still falling) — watch dev curve for the turn.
3. Evidence selection at rank 2+ still weak (domain 5/15, fresh 0/4) — candidates: more RAFT rows where gold lands late, or hard negatives mined by embedding similarity.
4. Official reranker/rank-mode A/B (recall@20 0.8333 → ordering gains available).
5. Casual paraphrase expansion: 15+ replacement rows from train-split parents NOT in legacy eval parents (list of 5 excluded parents in git history 2026-07-09 commit).
6. Gradio default adapter swap decision: fresh 0.73 is much better but false 5/8 is a safety-relevant regression — recommend holding until v3.1 fixes the false boundary.

## Latest Verification

- v3 train: 477 train / 52 dev rows, final_dev_loss 0.1763, no truncated rows, exit 0
- 4 eval runs exit 0 (deterministic): outputs/tuned_slm_qwen_domain_v3_{eval,official_eval,fresh_eval,fresh_chunk_oracle_eval}.json
- Diagnostics: outputs/tuned_slm_v3_diagnostic_report.json
- Leakage validation (pre-train): all overlaps 0; RAFT structure verified (positions/doc-count)
