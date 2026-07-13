# Phase C Parent-Window A/B

## Verdict

Immediate sibling context is **rejected**. It slightly improved citation and evidence overlap on the human partial slice, but did not improve partial joint success and caused a clear fresh-dev regression with a large latency increase.

The experiment kept retrieval fixed. Generated prompts exposed only retrieved anchor chunk IDs for citation, while text from the same parent's immediate `-1/+1` chunks was added without a citeable sibling ID. Already-retrieved sibling chunks were not duplicated.

## Results

| set | mode | retrieval hit | exact citation | partial joint | false joint | evidence recall | latency |
|---|---|---:|---:|---:|---:|---:|---:|
| human partial | chunk | 0.9000 | 0.5000 | 0.3000 | n/a | 0.2058 | 4.581s |
| human partial | sibling window | 0.9000 | 0.6000 | 0.3000 | n/a | 0.2355 | 6.518s |
| fresh_dev | chunk | 0.9545 | 0.5000 | 0.0000 | 0.8750 | 0.3066 | 3.180s |
| fresh_dev | sibling window | 0.9545 | 0.4091 | 0.0000 | 0.8750 | 0.2612 | 12.659s |

Retrieval IDs matched exactly for every row. Sibling text was actually added to 18/20 human-partial rows and 28/30 fresh-dev rows, so the negative result is not caused by an inactive window path. Generation context gold-hit rate did not increase on either set: the missing gold chunks were not immediate siblings of the retrieved anchors.

## Interpretation

- The extra context changed many answers, but it did not rescue any missing expected chunk.
- Human partial citation improved by two rows, but joint success remained six rows.
- Fresh-dev citation lost two rows and evidence support fell.
- Fresh-dev latency increased by roughly four times, and one false row produced an unsupported substantive answer.

The cross-set no-regression gate failed before domain/official expansion. Running another 150 generations could not change the promotion decision, so those expensive arms were intentionally not run.

Canonical retrieval, Gradio defaults, and frozen blind remain unchanged. The next controlled experiment is a separate deterministic-contextual-prefix index A/B.
