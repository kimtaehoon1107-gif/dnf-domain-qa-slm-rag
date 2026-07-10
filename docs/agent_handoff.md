# Agent Handoff - DNF Domain QA SLM/RAG

> Overwrite this file at handoff time. Keep the full history in `docs/project_progress_report.md` and durable project rules in `AGENTS.md`.

## Current Goal

v3.3 trained and evaluated (2026-07-10). **Best adapter to date: `outputs/slm_lora_qwen_domain_v3_3`** (partial-diverse data + 2 epochs). fresh 0.80 (best ever), fresh false 8/8 with true 14/16 simultaneously (first time), citation held at probe-best levels. Recommendation: **swap Gradio default to v3.3** (user decision pending). Remaining weak axis: partial 2/6 — errors now on the safe side (refuse instead of invent).

## Epoch probe finding (v3.2 data, 1 vs 2 epochs)

2 epochs passed all three promotion criteria with zero regressions: fresh exact citation 0.32→0.59 (the v3.2 citation decline was under-training — rank-1 prior dissolved before content-based selection consolidated), partial 1/6→2/6, gold-hit up (domain rank1 25/27, rank2 7/15). Dev loss plateaus at ~1.75-1.9 epochs → **2 epochs is the standard now; 3 would likely overfit.**

## v3 / v3.1 / v3.2 comparison

| | v3 | v3.1 | v3.2 |
|---|---|---|---|
| domain answerability | 0.925 (false 21/30) | 0.9917 | **0.9917 (false 29/30 held)** |
| official | 1.0 | 1.0 | 1.0 |
| fresh answerability | 0.7333 | 0.6333 | 0.6667 |
| fresh true | **15/16** | 11/16 | 12/16 |
| fresh partial | 2/6 | 2/6 | 1/6 ← now weakest |
| fresh false | 5/8 | 6/8 | **7/8** |
| fresh oracle false | 6/8 | 8/8 | **8/8** |
| fresh exact citation | **0.6364** | 0.5455 | 0.3182 ← declining |
| domain predicted ranks | 66/14/9 | 68/14/8 | 46/30/14 (fully spread) |
| dev loss (final) | 0.176 | 0.150 | **0.137** |

Fresh flips v3.1→v3.2: 0008 삭제날짜 false→true (contrastive target recovered), 0013 피로도 false→partial (half-recovered), 0028 weather true→false (fixed), 0019 partial→false (lost). Still refused: 0003/0004 (점검공지/클라패치 yes/no — their evidence parents are legacy-excluded from training, so this family needs OTHER notice/patch_note train docs, e.g. official_update_2927196).

Interpretation: contrastive coverage works — targeted families moved correctly and nothing swung back. But citation accuracy fell as the rank-1 prior dissolved (model now picks positions freely but not yet by content): domain exact citation 0.37→0.30, official 0.29→0.17, fresh 0.55→0.32.

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

## Post-v3.2 review consensus (Codex review + Claude verification, 2026-07-10)

- **Gradio default: HOLD, no exception.** Wrong-citation rates (domain 0.70, official 0.83 given any citation) make v3.2 unusable as a citation-forward demo. Earlier "if needed now, v3.2" hedge is withdrawn.
- **Title-overlap warnings (29) triaged: all KEEP.** Checked every warned row: answer-from-title token overlap max 0.14 — all are body-fact questions using the title only as topic anchor (matches how fresh eval questions name products). Criterion for future rows: reject only if the answer is derivable from the title; also mix in some non-title phrasings for diversity.
- **Promotion criteria for any new adapter** (per Codex review): fresh partial accuracy, exact citation, and predicted-citation-vs-gold hit — NOT dev loss, and "ranks spread" is not success; "gold hit" is.
- fresh partial confirmed model/data-bound (oracle also 1/6): retrieval work cannot help this axis.

## v3.3 results (all --deterministic --seed 42)

| | v3.2 (1ep) | probe (2ep) | v3.3 (2ep + 20 partial-diverse rows) |
|---|---|---|---|
| domain | 0.9917 | 0.9917 | 0.9917 (false 29/30) |
| official | 1.0 | 1.0 | 1.0 |
| fresh | 0.6667 | 0.70 | **0.80** (true 14/16, partial 2/6, false **8/8**) |
| fresh oracle | 0.70 | 0.7667 | **0.80** |
| exact citation f/d/o | 0.32/0.30/0.17 | 0.59/0.36/0.21 | 0.59/0.36/**0.25** |

Flips probe→v3.3: yes/no true rows 0003/0004/0013 all recovered; 0030 realtime-price false fixed; 0012 lost (its evidence doc is legacy-excluded → untrainable family, known limitation); partials 0018/0021 moved wrong-true → wrong-false (safer error direction). Unexpected mechanism: diverse partial data sharpened the fact-vs-decision boundary overall, fixing true/false rows rather than partial itself.

## Root-cause diagnostics (2026-07-10, no-training checks — read before adding data)

1. **Partial is NOT a data-volume problem.** Generated text on the 4 failing partial rows is the verbatim false-template refusal — the model never attempts decomposition. Causes: (a) **instruction-data concept mismatch**: `DEFAULT_RAG_INSTRUCTION` defines partial as "근거가 일부만 답하면" (evidence-coverage) while all partial training rows operationalize "질문이 사실+개인결정 혼합" (request-mix) — fix the instruction sentence at the next retraining; (b) **label-first output format** (`answerability:` is the first generated token) forces question classification before any generation — decision-led questions classify as false; (c) partial eval is 6 rows — nothing is judgeable until it is expanded. **Do not run a v3.4 partial-data round before (a)+(c).**
2. **Citation 0.356 is retrieval-bound, not model-bound.** Wrong citations that are same-parent siblings: only 6/58 (10%) — not a measurement artifact. exact-citation ceiling at top_k=3 = recall@3 = 0.478; model achieves 0.356 (=74% of ceiling; 93% gold-hit when gold is rank 1). ~3/4 of the gap is retrieval recall, ~1/4 model selection. **The citation round is a retrieval round.**

## Retrieval round result (2026-07-10)

Reranker A/B (bge-reranker-v2-m3 over hybrid top-20, `src/evaluate_reranker.py`): recall@3 domain 0.478→0.622, official 0.417→0.50, fresh 0.955→1.0; recall@1 domain 0.267→0.467. **Retrieval clearly improved.** End-to-end with v3.3 unchanged: official exact citation 0.25→0.375, but domain flat (0.356) and fresh DOWN (0.59→0.45, acc 0.80→0.77). Interpretation: **distribution mismatch** — v3.3 was trained on hybrid-context RAFT (near-random distractors); reranked top-3 packs uniformly plausible documents (hard negatives) the model never trained against. `--reranker-model` is integrated in retrieve.py but **OFF by default** (Gradio unchanged, still hybrid + v3.3).

This unifies three queued items into one evidence-backed v3.4 spec (do NOT run them separately):
- RAFT contexts rebuilt from **reranked retrieval** (natural hard negatives — also resolves the long-open distractor-hardness question)
- `DEFAULT_RAG_INSTRUCTION` partial clause rewritten to the request-mix concept
- 2 epochs, existing oversample recipe

Caveat re-confirmed: A/B recall@3 (0.622, top_k=20 pool) vs smoke retrieval_hit (0.578, top_k=3 pool) differ by candidate-pool size — standardize `candidate_k` before comparing retrieval numbers across scripts.

## Next Actions

1. **v3.4 (single round, evidence-backed spec above)**: reranked-context RAFT + instruction partial fix + 2ep. Success criteria: exact citation vs 0.622 ceiling, fresh answerability not regressing, partial judged only after eval expansion.
2. **Partial/fresh eval expansion** (human-written) — prerequisite for judging partial; also strengthens all fresh claims.
3. Standards stand: 2 epochs, diverse rows 1x (`make_gate_balanced.py`), template rows 3x, deterministic evals, direction-not-magnitude on fresh.

## Latest Verification

- v3 train: 477 train / 52 dev rows, final_dev_loss 0.1763, no truncated rows, exit 0
- 4 eval runs exit 0 (deterministic): outputs/tuned_slm_qwen_domain_v3_{eval,official_eval,fresh_eval,fresh_chunk_oracle_eval}.json
- Diagnostics: outputs/tuned_slm_v3_diagnostic_report.json
- Leakage validation (pre-train): all overlaps 0; RAFT structure verified (positions/doc-count)
