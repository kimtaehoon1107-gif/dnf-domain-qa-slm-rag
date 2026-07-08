# Agent Handoff - DNF Domain QA SLM/RAG

> Overwrite this file at handoff time. Keep the full history in `docs/project_progress_report.md` and durable project rules in `AGENTS.md`.

## Current Goal

Pre-v3 data/metric repairs are DONE and committed (git `70b129a`). Next milestone: v3 LoRA training on the repaired RAFT, but only after train-only casual paraphrase data is added.

## Current State (after Claude repair pass, 2026-07-08)

- **Canonical eval/train were regenerated and PROMOTED** with POS-filtered (kiwipiepy) anchor extraction:
  - `data/processed/domain_eval_set_expanded.jsonl` (120: true 80 / partial 10 / false 30)
  - `data/processed/domain_train_qa_expanded.jsonl` (320: true 240 / partial 20 / false 60)
  - Old files backed up as `*_pre_anchorfix_pos_20260708_222817.jsonl`
  - 30-row human audit: no verb-fragment/pasted-sentence questions remain. Known minor blemishes: one josa error in a false template ("브레이커이" → should be 브레이커가), a couple of awkward noun stacks ("장비 관련 변경 사용 방법은 뭐야?").
- **All prior v2 adapter eval numbers are now HISTORICAL** — the eval set changed. Do not compare new runs against them directly.
- Retrieval on the new eval (`outputs/domain_retriever_candidate_report_anchorfix_pos.json`):
  - recall@3 0.4778, recall@5 0.5667, recall@10 0.6333, recall@20 0.7444, MRR@10 0.3831, missing@20 23/90
  - Note: Codex's earlier anchorfix candidate scored higher (0.7889) partly because its broken span-pasting questions were trivially lexical-matchable. The lower number here is the more honest one.
- **RAFT regenerated with structural fixes** (`make_raft_dataset.py` updated):
  - gold position shuffled: citation rows at position 1/2/3 = 102/84/94 (was 279/279 at position 1)
  - false rows now get 3 documents like answerable rows (was 2 vs 3 — document count alone predicted the label during training)
  - `--gold-text chunk` used: gold doc is the full chunk, not the answer span (span mode made gold systematically the shortest doc and noise-free — two more shortcuts)
  - Files: `domain_raft_sample_expanded.jsonl` (300), `domain_raft_sample_expanded_gate_balanced.jsonl` (460: true 220 / partial 60 / false 180, 3x oversample recipe preserved)
- Leakage validation on promoted files: **all overlaps 0, no errors/warnings** (`outputs/domain_dataset_validation_report_v3.json`)
- New tooling options added:
  - `run_tuned_slm_smoke.py` / `run_tuned_slm_oracle_eval.py`: `--seed` (default 42) and `--deterministic` (CUBLAS workspace + `use_deterministic_algorithms(warn_only)`) — use `--deterministic` for all reported numbers
  - `finetune_lora.py`: `--dev-ratio` (e.g. 0.1) + `--eval-steps` for dev-loss tracking; `--seed`; SystemExit→RuntimeError convention fix
  - `evaluate_answers.py`: `faithfulness_when_citation_hit` — the unconditional `faithfulness_style` is circular for the extractive generator (answer is copied from retrieved text, so it scores ~1.0 even with wrong retrieval); only cite the conditional one in comparison tables
- Git: repository now has its first commit `70b129a` (code + docs + data; outputs/ ignored). Commit on every dataset/model version change from now on.

## Do Not Do

- Do not put `fresh_paraphrase_eval_set.jsonl` into training data (permanent held-out).
- Do not compare new eval runs against pre-2026-07-08 domain-eval numbers — the eval set changed.
- Do not report `answerability_accuracy` or unconditional `faithfulness_style` alone.
- Do not regenerate RAFT with `--gold-text span` (reintroduces length/noise shortcuts).

## Next Actions

1. Build train-only casual true/partial paraphrase rows (fresh-style wording, human-written or human-audited; verbatim-blocked against all three eval sets), append to domain train QA, regenerate RAFT (same command as below), re-validate.
2. Train v3 on the repaired gate-balanced RAFT:
   - `python src/finetune_lora.py --model-name Qwen/Qwen2.5-0.5B-Instruct --train-file data/processed/domain_raft_sample_expanded_gate_balanced.jsonl --output-dir outputs/slm_lora_qwen_domain_v3 --max-doc-chars 500 --max-seq-length 1536 --num-train-epochs 1 --per-device-train-batch-size 1 --gradient-accumulation-steps 4 --learning-rate 2e-4 --logging-steps 10 --save-steps 50 --bf16 --dev-ratio 0.1 --eval-steps 25`
   - Watch train-vs-dev loss divergence; consider stopping earlier or lowering lr if dev loss turns up.
3. Evaluate v3 with `--deterministic` on all three evals + chunk oracle; report answerability, exact citation, citation precision/recall/exact-set-match, and predicted-citation-rank distribution (the rank-1-copier check — expect it to spread if the shuffle worked).
4. Official reranker/rank-mode A/B (recall@20 is 0.8333 there, so ordering gains are available).
5. Analyze the 23 remaining missing@20 rows on the new domain eval (`analyze_domain_missing_retrieval.py`) — decide eval-fix vs retrieval-fix per row.

## RAFT regeneration command (reference)

```
python src/make_raft_dataset.py --docs data/processed/domain_doc_chunks.jsonl --qa data/processed/domain_train_qa_expanded.jsonl --exclude-eval-set data/processed/domain_eval_set_expanded.jsonl data/processed/official_eval_set.jsonl data/processed/fresh_paraphrase_eval_set.jsonl --output data/processed/domain_raft_sample_expanded.jsonl --max-rows 300 --distractors 2 --gold-text chunk --seed 42
```

Gate-balance recipe: duplicate each partial/false row 2 extra times (3x total), reassign raft_ids.

## Latest Verification

- `python -m compileall src` OK; `python src/run_smoke_tests.py` OK (post-commit)
- `validate_domain_dataset.py` on promoted files: all overlaps 0, errors [], warnings 0
- `analyze_raft_gold_positions.py` on new gate-balanced RAFT: positions 102/84/94, false-rows-with-gold 0
- Doc-count parity checked: true/partial/false all 3 docs per row
- git log: `70b129a` initial commit
