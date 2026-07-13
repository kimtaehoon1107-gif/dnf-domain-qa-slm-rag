# Clean Answer-Filtered Step-250 Results

## Verdict

The exploratory clean-from-base adapter is **not promoted**, and the remaining 14 training steps will not be completed. Answer-aware hard-negative cleaning fixed the most obvious contamination failure, but it did not solve conversational partial generalization or evidence selection.

| dev set | rows | retrieval hit | exact citation | partial joint | false joint | evidence recall |
|---|---:|---:|---:|---:|---:|---:|
| domain | 120 | 0.5222 | 0.3667 | 0.1000 | 1.0000 | 0.2418 |
| official | 30 | 0.6250 | 0.4167 | n/a | 1.0000 | 0.3312 |
| fresh_dev | 30 | 0.9545 | 0.5000 | 0.0000 | 0.8750 | 0.3066 |
| human partial dev | 20 | 0.9000 | 0.5000 | 0.3000 | n/a | 0.2058 |

## What Improved

- Domain false joint improved from control `27/30` to `30/30`.
- Fresh-dev false joint improved from control `5/8` to `7/8`.
- Domain citation avoided the unfiltered hard-negative regression (`0.3222`) and reached `0.3667`.
- Fresh-dev citation also improved over the unfiltered hard-negative arm (`0.4091` to `0.5000`).
- Unsafe-answer rate remained `0` on the measured safety-false rows.

This validates the data-cleaning decision: alternate valid evidence must not be labeled as a distractor.

## Why It Is Not Promoted

- Fresh-dev citation is below the control (`0.5000` vs `0.5909`).
- Fresh-dev partial joint fell from control `2/6` to `0/6`.
- Five of 21 retrieved-answerable fresh rows were over-refused.
- Human partial dev retrieved gold for 18/20 rows, but exact citation was only 10/20 and joint success 6/20.
- Domain retrieval still missed gold in top-3 for 43/90 answerable rows.

The remaining problem is not plausibly explained by 14 missing optimizer steps. It is a combination of candidate recall, evidence selection, and conversational partial calibration.

## Next

Keep Gradio on v3.3, keep reranker off, and do not open frozen blind. The next controlled experiment is the deferred Phase C parent-context A/B: chunk-only generation context versus retrieved chunk plus immediate `-1/+1` siblings, with retrieval and citations still scored at chunk level.

## Step-264 Completion Follow-Up

The remaining 14 steps were later completed from the same optimizer state and
training split. Step 264 preserved false/safety performance but regressed fresh
exact citation (`11/22 -> 9/22`) and human Partial exact citation (`10/20 ->
6/20`) and joint success (`6/20 -> 4/20`). Checkpoint-250 therefore remains the
selected clean baseline as a development-gated early-stopping choice. See
`docs/clean_answer_filtered_completed_results.md`.
