# Claude Handoff — DNF Domain QA SLM/RAG

Codex has completed the current pre-v3 diagnostic pass. Please review using these files as source of truth:

- `docs/agent_handoff.md`
- `docs/tuned_slm_failure_diagnosis.md`
- `outputs/domain_retriever_candidate_report.json`
- `outputs/official_retriever_candidate_report.json`
- `outputs/fresh_retriever_candidate_report.json`
- `outputs/raft_gold_position_report.json`
- `outputs/tuned_slm_v2_diagnostic_report.json`
- `outputs/tuned_slm_qwen_domain_gate_balanced_v2_*_chunk_oracle_eval.json`

Key confirmed findings:

- `answerability_accuracy=1.0` is not full answer quality.
- Exact citation remains low under normal retrieval:
  - domain: 0.2556
  - official: 0.3333
  - fresh: 0.2273
- Retriever-only top20 recall:
  - domain: recall@20 0.5222, MRR@10 0.3024
  - official: recall@20 0.8333, MRR@10 0.3896
  - fresh: recall@20 1.0000, MRR@10 0.8687
- Current RAFT gold-position bug is confirmed by Codex:
  - 279/279 citation rows place gold evidence at document position 1.
- `run_tuned_slm_oracle_eval.py` now supports `--oracle-mode span/chunk`.
- Chunk oracle results:
  - domain exact citation: 1.0000
  - official exact citation: 1.0000
  - fresh answerability: 0.5667
  - fresh exact citation: 0.4091

Recommended review focus:

1. Review whether `domain` top20 missing rows are mostly eval-quality, chunking, or candidate-generation failures.
2. Review whether `official` should prioritize reranking, since recall@20 is 0.8333 but rank1 remains weak.
3. Review RAFT v3 design before any retraining:
   - randomize gold document position,
   - put hard negatives before gold,
   - supervise non-first gold citations,
   - add train-only fresh-style true/partial paraphrases.
4. Keep `fresh_paraphrase_eval_set.jsonl` permanently held out.

Do not recommend v3 training until the domain missing@20 rows are analyzed.
