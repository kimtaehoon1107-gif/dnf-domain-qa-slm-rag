# Policy revision and monthly-item pre-generation binding round

Date: 2026-07-27

## Evaluation status

- The official sealed one-shot result remains `37/64`.
- The sealed 64-question artifact was not rewritten.
- This round is an adaptive diagnostic over previously inspected cases. It is
  not a new generalization score and does not authorize production promotion.
- Semantic fallback retrieval remains disabled.

## Changes

### Policy revision identity

For policy effective-date requirements, model-visible evidence is now bound
before generation by:

```text
requested policy subject
+ requested revision/year
+ effective-date temporal role
```

This prevents a current policy header or a sibling mobile-policy revision from
competing with the explicitly requested policy revision.

### Monthly item record binding

For explicit monthly-item requirements, model-visible evidence is now bound
before generation by:

```text
month
+ dnf_monthly_item source
+ item record
+ requested attribute
+ value
```

Adjacent label/value pairs such as `거래타입\n교환가능` and
`상점판매가\n4,000만 골드` are exposed as exact evidence units. Markdown
record headings such as `# [6월 이달의 아이템]` are accepted, while inline
mentions such as `사용 시 [7월]...` are not treated as new record boundaries.

### Verifier and scorer correction

For `enum`, `entity`, and `entity_list`, the exposed typed value must occur in
the selected evidence. The scorer also requires a citation to cover the full
approved evidence unit; a label-only or one-character overlap cannot receive
canonical-evidence credit.

This correction was required after the first slot 61 diagnostic exposed the
label `거래타입` while the previous scorer incorrectly credited the answer.
The corrected retry exposed `교환가능` and `4,000만 골드`.

## Gold addendum

The separate reviewed equivalent-evidence addendum now contains slots
`8, 31, 41, 47`. The sealed artifact remains byte-identical.

- Slot 31: the official Seria Shop evidence directly states a character-level
  maximum of ten presets.
- Slot 47: the official FAQ directly binds a 1:1 inquiry to a processing
  duration of three to five days.
- Slot 40 was not added because its frozen gold is already valid; its prior
  failure was a generation-protocol issue rather than missing gold evidence.

## Targeted Qwen3 8B diagnostic

Model: `qwen3-8b:ctx8192`

Retrieval was not re-executed. Eight stored product-router candidate pools were
reused, with one new generation call per question.

| Result | Slots |
|---|---|
| Recovered previous errors | `1, 6, 60, 61, 63` |
| Preserved previous correct cases | `41, 57, 59` |
| Persistent errors | none |
| New regressions | none |

Metrics:

- typed-value complete: `8/8`
- false-full: `0`
- generation errors: `0`
- exact citation coordinates: `100%`
- mean / p50 / p95 latency: `7.73s / 8.03s / 12.12s`
- input / output tokens: `10,102 / 692`

Slot 63 is now a correct partial answer: the July price is answered from the
July record and the unsupported August item name is withheld.

The narrow frozen-gold evidence metric is `7/8` because slot 41 uses a reviewed
equivalent official policy header. The equivalent unit is recorded in the
separate addendum.

## Replay warning

The post-generation verifier replay over stored historical outputs is not
comparable after pre-generation binding changes the prompt evidence-ref
namespace. Its apparent `50 -> 48` and slots `57, 59` regressions are caused by
old `E` references no longer existing in the rebuilt prompt, not by semantic
answer regressions. Do not use that replay for promotion or headline scoring.

The targeted new-generation diagnostic above is the valid measurement for this
prompt-binding change.

## Shadow sufficiency gate

The full 64-question set was inspected in shadow mode only:

- requirements: `96`
- assessable requirements: `21`
- would-trigger requirements: `2`
- would-trigger slots: `5, 7`
- fallback retrieval calls: `0`
- generation calls: `0`

The earlier slot 62 false trigger was removed by correcting monthly record
heading recognition. Slot 7 is a valid unsupported case, so these results still
do not justify enabling semantic fallback.

## Verification

- focused tests: `51 passed`, `7 subtests passed`
- full repository tests: `789 passed`, `54 subtests passed`
- warnings: `3` dependency deprecation warnings
- `git diff --check`: passed

## Verdict

The narrow policy-revision and monthly-item pre-generation bindings are
diagnostically successful and regression-tested. They should remain an
unpromoted candidate until an untouched evaluation set confirms that the
targeted recovery generalizes.

Do not rerun or retune the sealed 64 for a new headline score. The next
meaningful step is an untouched evaluation run; semantic fallback should be
considered only if that set reveals real retrieval misses.

## Artifacts

- Targeted generation:
  `reports/v3/typed_evidence_ref_policy_month_binding_qwen3_8b_final8_20260727.json`
- Shadow gate:
  `reports/v3/typed_evidence_ref_sufficiency_shadow_post_binding_v2_full64_20260727.json`
- Equivalent-evidence addendum:
  `data/v3/evaluation/typed_evidence_ref_generalization_64_equivalent_evidence_addendum_20260727.jsonl`
