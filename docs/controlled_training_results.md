# Measurement-Repaired Controlled SLM Experiment

## Scope

All three arms use the same 408 unique QA groups, parent-document-held-out dev split, 900-character query-aware evidence window, two epochs, and deterministic evaluation. The pending blind-test candidate was not queried.

- `control`: legacy instruction + random distractors
- `instruction_only`: request-mix instruction + the same random-distractor recipe
- `hard_negative_only`: legacy instruction + reranker-mined distractors

## Hybrid Retrieval

### domain

| arm | ans. acc | true | partial | false | exact citation | partial joint | false joint | evidence recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| control | 0.975 | 1.000 | 1.000 | 0.900 | 0.356 | 0.100 | 0.900 | 0.236 |
| instruction_only | 0.992 | 1.000 | 1.000 | 0.967 | 0.344 | 0.000 | 0.967 | 0.244 |
| hard_negative_only | 0.992 | 0.988 | 1.000 | 1.000 | 0.322 | 0.200 | 1.000 | 0.221 |

### official

| arm | ans. acc | true | partial | false | exact citation | partial joint | false joint | evidence recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| control | 1.000 | 1.000 | - | 1.000 | 0.333 | - | 1.000 | 0.231 |
| instruction_only | 1.000 | 1.000 | - | 1.000 | 0.292 | - | 1.000 | 0.262 |
| hard_negative_only | 1.000 | 1.000 | - | 1.000 | 0.250 | - | 1.000 | 0.309 |

### fresh_dev

| arm | ans. acc | true | partial | false | exact citation | partial joint | false joint | evidence recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| control | 0.767 | 0.938 | 0.500 | 0.625 | 0.591 | 0.333 | 0.625 | 0.336 |
| instruction_only | 0.733 | 0.938 | 0.333 | 0.625 | 0.591 | 0.167 | 0.625 | 0.331 |
| hard_negative_only | 0.767 | 0.812 | 0.500 | 0.875 | 0.409 | 0.167 | 0.875 | 0.265 |

## Reranker Follow-up

| arm | set | retrieval hit | exact citation | partial joint | false joint | evidence recall |
|---|---|---:|---:|---:|---:|---:|
| control | domain | 0.578 | 0.444 | 0.200 | 0.833 | 0.281 |
| control | fresh_dev | 1.000 | 0.591 | 0.167 | 0.625 | 0.339 |
| hard_negative_only | domain | 0.578 | 0.278 | 0.100 | 1.000 | 0.186 |
| hard_negative_only | fresh_dev | 1.000 | 0.318 | 0.167 | 0.750 | 0.214 |

## Verdict

No new adapter is promoted. The instruction-only change improved some refusal rows but did not improve partial joint success or citation. The unfiltered hard-negative arm learned stronger refusal while losing evidence selection; diagnostics found valid duplicate evidence mislabeled as distractors.

The Gradio default remains v3.3 and the reranker remains off. An answer-aware hard-negative artifact has been regenerated with exact/high-overlap evidence contamination removed, but it is intentionally not trained in this round.

`fresh_paraphrase_eval_set.jsonl` is reported as `fresh_dev`, not a final blind test. The new blind candidate remains pending human review and was never passed to retrieval or generation.
