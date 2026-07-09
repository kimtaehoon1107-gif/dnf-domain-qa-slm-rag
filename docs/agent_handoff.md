# Agent Handoff - DNF Domain QA SLM/RAG

> Overwrite this file at handoff time. Keep the full history in `docs/project_progress_report.md` and durable project rules in `AGENTS.md`.

## Current Goal

v3.1 trained and evaluated (2026-07-09). The false boundary was largely fixed (domain false 21/30 → 29/30, fresh oracle false 8/8) but 4 fresh **yes/no-phrased true questions** flipped to refusal (fresh true 15/16 → 11/16). Next round (v3.2): contrastive true coverage for yes/no casual phrasings.

## v3 vs v3.1 (both exist; neither dominates)

| | v3 | v3.1 |
|---|---|---|
| domain answerability | 0.925 (false 21/30) | **0.9917 (false 29/30)** |
| official | 1.0 | 1.0 |
| fresh answerability | **0.7333** (true 15/16, false 5/8) | 0.6333 (true 11/16, false 6/8) |
| fresh chunk-oracle | 0.7667 (false 6/8) | 0.7667 (**false 8/8**) |
| fresh exact citation | **0.6364** | 0.5455 |
| dev loss (final) | 0.176 | **0.150** |

Fresh flips v3→v3.1: gains = abuse row now refused (0027), one partial recovered (0019); losses = 4 true rows refused (0003 게임 꺼야 돼 있어?, 0004 고쳤어?, 0008 삭제 날짜 언제야?, 0013 피로도 써?) — all yes/no casual phrasings; plus 0018 partial→true, 0028 weather partial→true(worse). Adapters: `outputs/slm_lora_qwen_domain_v3`, `outputs/slm_lora_qwen_domain_v3_1`.

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

## Next Actions (v3.2 round)

1. **Contrastive true coverage** (the principled fix for the seesaw): the 4 lost fresh true rows are yes/no casual phrasings ("~돼 있어?", "~고쳤어?", "~써?", "삭제 날짜 언제야?"). Add ~15-20 train-only TRUE rows in exactly these families, grounded in train-split chunks (avoid the 5 legacy-eval parents), ideally topic-matched neighbors of the refusal categories so surface cues cannot separate labels. Human-audit before append.
2. Keep the 28 casual false rows at 1x — do not raise to 2x/3x until contrastive true data is in (raising volume now would deepen the over-refusal swing).
3. Consider 2 epochs after (dev loss still falling at 0.150) — separate experiment, do not combine with data change.
4. Evidence selection at rank 2+ still weak; official reranker/rank-mode A/B still pending.
5. Gradio default adapter swap: keep holding. v3 is the helpfulness-leaning candidate, v3.1 the safety-leaning one; neither is clean enough. Small-eval caveat: fresh has only 16 true / 8 false rows, so single-row flips move percentages by 6-12pp — judge direction, not magnitude.

## Latest Verification

- v3 train: 477 train / 52 dev rows, final_dev_loss 0.1763, no truncated rows, exit 0
- 4 eval runs exit 0 (deterministic): outputs/tuned_slm_qwen_domain_v3_{eval,official_eval,fresh_eval,fresh_chunk_oracle_eval}.json
- Diagnostics: outputs/tuned_slm_v3_diagnostic_report.json
- Leakage validation (pre-train): all overlaps 0; RAFT structure verified (positions/doc-count)
