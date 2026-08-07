# Router backbone mixed-answerability metrics (v3.2)

Development-only re-scoring of the frozen 95-question backbone on **two axes**. It
changes no runtime, no gold, and no frozen report. It reads only the already-frozen
`answerability_profile` and `partial_requirements_in_question_order` that were authored
before any planner output was visible (`new_planner_output_visible_during_ground_truth_authoring`).

## Why

The legacy evaluator collapses every non-`false` question into one `answerable_docs`
bucket of 82:

```python
if ground_truth["answerability_label"] != "false":
    return "answerable_docs"
```

This merges `docs_only` (69) and `mixed` (13). A *correct* mixed answer — official part
answered, personal/realtime part honestly abstained — is a `partial_answer`, which the
legacy metric records as `false_partial`. Worse, a mixed answer that *over-claims* the
personal part (`full_answer`) is recorded as `grounded`. Both are measurement errors, not
model errors.

## Answerability profile (frozen, 95 questions)

| profile | count | scored as |
|---|---:|---|
| `docs_only` | 69 | docs-only grounding |
| `mixed` | 13 | mixed-partial correctness |
| `non_docs_only` | 10 | reject / realtime |
| `docs_only_official_fact_without_current_evidence` | 3 | reject / realtime |

## Mixed scoring (per question)

Requirement indices `1..N` are split by `answerable_from_docs`:

- `docs_required` = indices answerable from documents
- `non_docs_required` = personal / realtime indices

From the frozen Arm0 decision:

- `docs_all_supported` = every `docs_required` index is `supported_exact`
- `no_non_docs_claimed` = no `non_docs_required` index is supported
- `docs_evidence_cited` = all gold evidence groups cited (legacy `all_groups_cited`)

Labels (mutually informative, reported as counts):

| label | meaning |
|---|---|
| `correct_mixed_partial` | `partial_answer` + docs complete + personal abstained |
| `mixed_overclaim` | a personal/realtime requirement was answered as if from docs (safety risk) |
| `mixed_overreject` | an answerable official requirement was rejected |
| `mixed_missing_evidence` | official part marked supported but gold evidence not cited |

## Two-axis (span-value) layer

`docs_complete_span_strict` additionally requires that each supported `docs_required`
requirement passes the mechanical value-shape check (`requirement_value_shape`): a
requirement asking for a %/amount/date/duration must actually cite that value, not a
header. This folds the B1 span-level axis into the docs-completeness check so a header-only
citation does not count as complete.

## Preservation

- Legacy collapsed metrics (`grounded 73/82`, `false_partial 2/82`, ...) are reproduced and
  reported side by side as `legacy_proxy`. They are never deleted or replaced.
- The evaluator asserts it reproduces the frozen Arm0 score before re-scoring.
- All outputs are content-addressed immutable artifacts. No promotion.
