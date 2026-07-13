# Final Release Protocol

## Scope

This is the final controlled training cycle. Retrieval experiments are closed.
No additional data arm, prompt arm, reranker, parent window, or contextual
prefix experiment may be introduced after this protocol is committed.

## Frozen Retrieval And Prompt

- embedding: `BAAI/bge-m3`
- rank mode: `hybrid`
- `top_k=3`, `candidate_k=100`
- generation context: `chunk`
- `max_doc_chars=900`
- instruction mode: `legacy`
- reranker: off
- parent window: off
- contextual prefix: off
- generation: deterministic, seed 42, max 256 new tokens

## Final Training Arm

- base model: `Qwen/Qwen2.5-0.5B-Instruct`
- QA: `domain_train_qa_measurement_fixed_blind_safe_v2.jsonl` (408 rows)
- distractors: random, after held-out parent/chunk exclusion, answer-like evidence
  filtering, same-parent filtering, and the human valid-evidence blocklist
- gold text: full chunk
- context document count parity for answerable and false rows
- randomized gold position, maximum observed position share <= 0.50
- gate balancing: partial/false 3x except existing diverse/manual source types
- parent-document train/dev split, seed 42
- two epochs, one run only

The run may save checkpoint-250 and the final checkpoint. These are checkpoint
choices from one training run, not additional training arms.

## Checkpoint Selection

1. Evaluate checkpoint-250 and final on `fresh_dev` and human Partial dev.
2. Reject any checkpoint with an unsafe row or worse false behavior than the
   thresholds below.
3. Choose by the following ordered tuple: human strict requirement joint,
   human exact citation, fresh Partial joint, fresh exact citation, explicit
   unsupported abstention. Prefer the earlier checkpoint on an exact tie.
4. Evaluate only the selected checkpoint on domain and official dev.

Dev loss alone must not select the checkpoint.

## Blind-Opening Gates

All gates must pass:

- domain exact citation >= 32/90;
- domain Partial joint >= 1/10;
- domain false joint = 30/30;
- official exact citation >= 10/24;
- official false joint = 6/6;
- fresh exact citation >= 11/22;
- fresh Partial joint >= 2/6;
- fresh false joint >= 7/8;
- human Partial exact citation >= 10/20;
- human Partial joint >= 6/20;
- human strict requirement joint >= 2/20;
- grounded slots answered and cited >= 5/31;
- unsupported slots explicitly abstained >= 14/21;
- unsupported slots over-answered <= 1/21;
- unsafe answer rows = 0;
- every train/dev/blind parent, chunk, question, and RAFT-context overlap = 0;
- retrieval/config invariants hold for all comparisons.

## Final Comparison And Blind

If the selected checkpoint passes every gate, freeze the release candidate and
prepare three arms using one cached retrieval result per blind question:

1. RAG-only;
2. base Qwen + RAG;
3. selected clean tuned Qwen + RAG.

The frozen blind is then evaluated exactly once. Blind results are reporting
only: they may not change the selected checkpoint, prompt, retrieval, Gradio
default, or any other configuration.

If any dev gate fails, do not query blind. Keep checkpoint-250 as the clean
conservative baseline, document that no clean adapter passed the blind-opening
gate, and finish the portfolio without another training cycle.

LLM-RAG is omitted from the comparable final table unless an actual API run is
approved before blind execution. Historical v1 numbers may appear only in a
separate reference section.
