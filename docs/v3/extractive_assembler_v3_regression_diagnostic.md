# Assembler v3 regression attribution and aggregate repair contract

## Frozen regressions

The mechanical assembler v3 improved adaptive-dev evidence-group citation from
47/59 to 54/59 and eligible fully-cited questions from 43/54 to 50/54. Its
downgraded authored canary had zero regression. Promotion was blocked by three
adaptive-dev evidence-group and question regressions.

The three groups are traced in this fixed order: enumeration, segmentation,
selected-chunk availability, K boundary, threshold, query representation, and
per-requirement versus whole-question behavior. Gold IDs and spans are used only
for this diagnostic attribution and aggregate scoring, never as runtime input.

Attribution found:

- two `SEGMENTATION_BOUNDARY` groups: one gold span crosses three adjacent
  sentence segments and one crosses an adjacent label/value pair;
- one `K_BOUNDARY` group: the exact answer-bearing segment ranks fifth with
  score 0.7699002;
- zero `ENUM_MISS`, `SELECTION_BOUND`, or `THRESHOLD` primary failures.

All three have a frozen planner requirement and an acceptable chunk in the
stage2 selected evidence.

## K-only aggregate diagnostic

The existing frozen v3 scores are evaluated with the original threshold grid
and K from 1 through 6. K=5, threshold=.001 reaches regression zero, dev 58/59,
and 73/73 eligible fully-cited questions, but selects 4.970803 segments per
supported requirement. Therefore K-only repair violates the unchanged
over-selection gate and is not eligible for promotion.

## Uniform structural repair

The maximum observed boundary width is three. The repair therefore adds, for
every selected chunk and without inspecting question text, exact contiguous
merge candidates for every adjacent base-segment window of size two and three.
The gap between adjacent segments must contain whitespace only. Base sentence
and table-row candidates remain. Merge candidates record exact source offsets
and are scored by the unchanged `BAAI/bge-reranker-v2-m3` model.

The adjusted grid is frozen before merged scores are viewed:

- threshold: `0`, `.001`, `.005`, `.01`, `.025`, `.05`, `.1`, `.2`, `.35`,
  `.5`, `.65`, `.8`, `.9`, `.95`;
- K: `1`, `2`, `3`, `4`, `5`, `6`.

All 84 configurations use one immutable score artifact. There are no
question-specific merges, thresholds, K values, keywords, or query rewrites.

## Adjusted gate

The repair is eligible only if all conditions hold:

- adaptive-dev evidence-group hits are at least the current v3 result 54/59;
- eligible fully-cited questions are at least the current v3 result 69/73;
- evidence-group and question strict regressions are both zero;
- mean selected segments per supported requirement is at most 3;
- exact-slice validity is 100% and malformed output is zero;
- assembler LLM calls remain zero.

Among passing configurations, maximize dev hits, then fully-cited questions,
then minimize mean selections, prefer smaller K, then higher threshold. If no
configuration passes, preserve a development-only representative by minimizing
group regression, then question regression, maximizing the two performance
counts, minimizing selections, preferring smaller K, then higher threshold.

## Scope

This is diagnostic plus one uniform structural aggregate repair. Planner,
stage2 chunk reranker, retrieval, query representation, entailment,
answerability, temporal policy, and generation are unchanged or parked. There
is no LLM, training, new canary, individual dev tuning, or canonical promotion.
