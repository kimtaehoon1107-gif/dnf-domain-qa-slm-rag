# Final Clean Release Results

## Verdict

The final blind-safe training cycle is complete, but no checkpoint passed the
predeclared development gates. The frozen blind set was therefore not queried.
`checkpoint-250` is retained as a clean development baseline, not as a
blind-validated release model. No further training cycle is part of this
portfolio release.

Authoritative machine-readable results:

- `reports/final_random_control_training_manifest.json`
- `reports/final_random_control_release_decision.json`
- `reports/final_dev_system_comparison.json`
- `reports/domain_dataset_validation_random_control_blind_safe_final.json`
- `reports/domain_raft_random_control_blind_safe_final_audit.json`

## Frozen Configuration

| Component | Value |
|---|---|
| Embedding | `BAAI/bge-m3` |
| Ranking | hybrid dense + lexical |
| Retrieval | `top_k=3`, `candidate_k=100` |
| Context | chunk-only, query-aware 900 characters |
| Prompt | legacy shared prompt from `src/prompt_format.py` |
| Generation | deterministic greedy decoding, seed 42, 256 new tokens |
| Base model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Reranker / parent window / prefix | off / off / off |

The contextual-prefix and parent-window experiments were rejected before this
cycle. RRF and the reranker also remain non-canonical.

## Data Integrity

The final QA file contains 408 reviewed, blind-safe rows. The gate-balanced
random-control RAFT file contains 576 rows (`true=277`, `partial=92`,
`false=207`). Its SHA-256 is
`a092f49e13654fc2c69dc3b352dec6e8ddfa6aa0a3108f3b8214d22fa18b6730`.

Validation proved:

- train/dev/eval/blind parent overlap: `0`;
- train/dev/eval/blind chunk overlap: `0`;
- train/dev/eval/blind question overlap: `0`;
- RAFT context overlap with held-out parents/chunks: `0`;
- gold evidence visibility: `369/369`;
- gold positions: `117 / 124 / 128`, maximum share `0.3469`;
- 1,359 distractors with exact evidence span: `0`;
- distractors with evidence-token recall at least `0.5`: `0`;
- human-blocked valid-evidence pairs present as negatives: `0`.

## Final Training

One clean run was started from the base Qwen model. It used a parent-document
split (`528 train / 32 dev`), two epochs, completion-only loss, LoRA rank 16,
learning rate `2e-4`, gradient accumulation 4, and FP16. It completed `264/264`
steps with final dev loss `0.1300`; no rows were skipped.

The run produced `checkpoint-250` and the completed step-264 adapter. These are
checkpoint choices from one run, not separate training arms.

## Checkpoint Decision

Selection followed the frozen ordered tuple: human strict requirement joint,
human exact citation, fresh Partial joint, fresh exact citation, then explicit
unsupported abstention.

| Metric | checkpoint-250 | step-264 final |
|---|---:|---:|
| fresh exact citation | 14/22 | 12/22 |
| fresh Partial joint | 3/6 | 2/6 |
| fresh false joint | 5/8 | 6/8 |
| human Partial exact citation | 12/20 | 11/20 |
| human Partial joint | 8/20 | 7/20 |
| human strict requirement joint | 3/20 | 2/20 |
| grounded slots answered and cited | 11/31 | 8/31 |
| unsupported slots explicitly abstained | 8/21 | 8/21 |
| unsupported slots over-answered | 0/21 | 0/21 |
| unsafe answers | 0 | 0 |

`checkpoint-250` wins the frozen selection tuple. Both checkpoints fail the
same blind-opening gates:

- fresh false joint required at least `7/8`, observed `5/8` and `6/8`;
- explicit unsupported abstention required at least `14/21`, observed `8/21`
  for both.

Because the failure occurred before domain/official expansion, those two dev
sets were not used for this final checkpoint decision. The frozen blind remains
untouched by retrieval and generation.

## Three-System Development Comparison

This comparison is development-only. `fresh_dev` is adaptive and is not a
final held-out test.

### Fresh Dev

| System | schema | true | partial | false | exact citation | Partial joint | false joint | unsafe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RAG-only | 30/30 | 16/16 | 0/6 | 5/8 | 14/22 | 0/6 | 5/8 | 0 |
| Base Qwen + RAG | 0/30 | 0/16 | 0/6 | 0/8 | 0/22 | 0/6 | 0/8 | 2 |
| Clean tuned Qwen + RAG | 30/30 | 15/16 | 3/6 | 5/8 | 14/22 | 3/6 | 5/8 | 0 |

All three arms received the same retrieved chunks (`21/22` answerable rows hit
at top 3). Base Qwen frequently produced plausible prose but ignored the
required line schema, invented unsupported content, and gave substantive
answers on both safety rows. The safety evaluator therefore falls back to raw
generation text when structured parsing fails.

### Human Partial Dev

| System | schema | exact citation | Partial joint | strict requirement joint | grounded+cited | explicit abstention |
|---|---:|---:|---:|---:|---:|---:|
| RAG-only | 20/20 | 6/20 | 0/20 | 0/20 | 6/31 | 0/21 |
| Base Qwen + RAG | 0/20 | 0/20 | 0/20 | 0/20 | 0/31 | 0/21 |
| Clean tuned Qwen + RAG | 20/20 | 12/20 | 8/20 | 3/20 | 11/31 | 8/21 |

The tuned adapter clearly teaches output structure, evidence citation, and
mixed Partial behavior. Its remaining failure is not “the model learned
nothing”; it is the unsupported side of mixed requests. The model often omits
an explicit refusal even when it answers and cites the grounded portion.

## Reproduction

Validate the frozen data:

```powershell
python src/validate_domain_dataset.py `
  --train-qa data/processed/domain_train_qa_measurement_fixed_blind_safe_v2.jsonl `
  --raft data/processed/domain_raft_random_control_blind_safe_final_gate_balanced.jsonl `
  --output reports/domain_dataset_validation_random_control_blind_safe_final.json

python src/audit_raft_distractors.py `
  --raft data/processed/domain_raft_random_control_blind_safe_final_gate_balanced.jsonl `
  --output reports/domain_raft_random_control_blind_safe_final_audit.json
```

Reproduce the final training only if a fresh run is intentionally desired:

```powershell
python src/finetune_lora.py `
  --model-name Qwen/Qwen2.5-0.5B-Instruct `
  --train-file data/processed/domain_raft_random_control_blind_safe_final_gate_balanced.jsonl `
  --output-dir outputs/slm_lora_random_control_blind_safe_final `
  --max-doc-chars 900 --max-seq-length 3072 `
  --num-train-epochs 2 --per-device-train-batch-size 1 `
  --gradient-accumulation-steps 4 --learning-rate 2e-4 `
  --logging-steps 10 --save-steps 50 `
  --dev-ratio 0.1 --dev-group-by parent_doc_id --eval-steps 25 `
  --gradient-checkpointing --fp16 --seed 42
```

Regenerate the development comparison summary after running the three arms:

```powershell
python src/summarize_final_dev_comparison.py `
  --rag-prefix reports/final_comparison_rag_only `
  --base-prefix reports/final_comparison_base_slm `
  --tuned-prefix reports/final_random_control_step250 `
  --release-decision reports/final_random_control_release_decision.json `
  --output reports/final_dev_system_comparison.json
```

## Final Scope

- The Gradio default mode remains RAG-only.
- Tuned mode points to the clean blind-safe `checkpoint-250` development
  baseline and uses the frozen 900/256 settings.
- Base SLM + RAG is available as an explicit comparison mode.
- LLM-RAG remains unconfigured and historical v1 figures are reference-only.
- No blind score or production-quality claim is made.
- The next research cycle, if ever funded, must begin with a new human-reviewed
  Partial-vs-unsupported contrast design. It is outside this release.
