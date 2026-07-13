# Clean Answer-Filtered 264-Step Completion

## Verdict

The interrupted clean checkpoint was successfully resumed from step 250 and
completed at step 264. The completed adapter is **not selected**: it preserves
false/safety behavior but regresses citation and human Partial performance.
Checkpoint-250 remains the selected clean conservative baseline as an
evidence-based early-stopping choice.

The frozen blind set was not queried, and Gradio was not changed.

## Completion Integrity

- Base model: `Qwen/Qwen2.5-0.5B-Instruct`
- Training file SHA-256:
  `491951a8b974a2d3c44ccdd8298987d7e4603ba77e662f235bd2ca9cc5eb6def`
- Resume source: clean checkpoint-250 copy with the same adapter hash and the
  stale incompatible `scaler.pt` removed
- Final step: `264/264`, two epochs
- Split: `528 train / 32 dev`, parent/group overlap `0`
- Skipped train/dev rows: `0/0`
- Final dev loss: `0.1345` (checkpoint-250 last dev loss: `0.1367`)
- Final adapter:
  `outputs/slm_lora_answer_filtered_blind_safe_v2_completed`

The resume warning concerned only logging/save intervals (`10/50` in the saved
trainer state versus `5/25` in the resume command). Data, optimizer state,
learning rate, model, split, seed, and model-affecting hyperparameters were
unchanged.

## Checkpoint-250 Versus Step-264

| dev set | metric | step 250 | step 264 | delta |
|---|---|---:|---:|---:|
| domain | exact citation | 33/90 | 32/90 | -1 |
| domain | partial joint | 1/10 | 1/10 | 0 |
| domain | false joint | 30/30 | 30/30 | 0 |
| domain | unsafe safety rows | 0/9 | 0/9 | 0 |
| official | exact citation | 10/24 | 10/24 | 0 |
| official | false joint | 6/6 | 6/6 | 0 |
| fresh_dev | exact citation | 11/22 | 9/22 | -2 |
| fresh_dev | partial joint | 0/6 | 0/6 | 0 |
| fresh_dev | false joint | 7/8 | 8/8 | +1 |
| human Partial | exact citation | 10/20 | 6/20 | -4 |
| human Partial | partial joint | 6/20 | 4/20 | -2 |
| human Partial | strict requirement joint | 2/20 | 2/20 | 0 |

Requirement-level regressions are also clear:

- grounded slots answered: `6/31 -> 5/31`;
- grounded slots answered and cited: `5/31 -> 4/31`;
- grounded slots over-refused: `23/31 -> 26/31`;
- unsupported slots explicitly abstained: `14/21 -> 10/21`;
- unsupported slots omitted: `6/21 -> 11/21`.

The lower dev loss did not translate into better end-task behavior. The final
14 steps made the model more conservative on fresh false questions while
weakening evidence selection and Partial completion.

## Final Use

- Use checkpoint-250 as the clean conservative baseline in portfolio tables.
- Describe it explicitly as an early-stopped checkpoint selected by development
  gates, not as a completed two-epoch model.
- Keep step-264 as a documented rejected completion/over-training check.
- Do not run frozen blind for either adapter because neither passed all
  development promotion gates.

Machine-readable comparison:
`reports/clean_answer_filtered_completed_comparison.json`.
