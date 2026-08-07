# Product router semantic binding round — 2026-07-27

## Evaluation role

This round is adaptive diagnosis over the already inspected generalization-64
set. It does not replace the official sealed one-shot result (`37/64`) and is
not a production promotion result.

The current router and prompt-reduction baseline was frozen first in commit
`7e38005`.

## Reviewed equivalent evidence

The sealed 64-row artifact was not modified. Two official equivalent evidence
units omitted by the original narrow gold were recorded in a separate
addendum:

- slot 8: an official notice directly states the same Seria shop location;
- slot 41: the current official policy header binds the same revision to
  `2026-03-15`.

Artifact:

`data/v3/evaluation/typed_evidence_ref_generalization_64_equivalent_evidence_addendum_20260727.jsonl`

## Sufficiency gate shadow

The proposed fallback gate was evaluated without executing retrieval or
generation.

```text
requirements:                    96
assessable registered relations: 21
would trigger:                    2
triggered slots:                  5, 7
fallback retrieval calls:         0
generation calls:                 0
```

Slot 5 is already a no-response case. Slot 7 is correctly unsupported for the
requested fixed time, so a real second retrieval attempt would be unnecessary
there. The gate therefore remains shadow-only and semantic fallback remains
disabled.

## Binding verifier changes

Two general fail-closed checks were added:

```text
policy:
requested policy identity
+ explicit question year when present
+ active account-policy revision effective date

monthly item:
requested month
+ local item record
+ requested relation/attribute
+ selected value
```

The monthly check uses the local source record around the selected coordinate.
It does not accept a document title or a later navigation label as proof that
an earlier sibling table value belongs to the requested monthly item.

## Verifier-only replay

Stored candidates and stored Qwen outputs from the product-router run were
reused. There were no new model or retrieval calls.

| metric | before | after |
|---|---:|---:|
| adaptive gold-value complete | 50/64 | 50/64 |
| regressions | — | 0 |
| changed slots | — | 1, 6, 60, 61, 63 |

Every changed answer was already incorrect:

- slot 1: Sera terms question selected the mobile/policy revision date;
- slot 6: a 2025 policy-change notice selected the current 2026 revision;
- slots 60, 61, 63: a 7월 monthly-item requirement selected values from an
  earlier sibling special-item table.

The verifier changed those wrong supported values into safe abstentions. It
did not increase answer accuracy, but it removed the targeted wrong exposure
without regressing an existing correct case.

## Replay compatibility warning

An older requirement-reduction artifact was also replayed. It appears to
regress slot 47, but the stored model output references `E19` while the rebuilt
current prompt no longer contains that evidence ref. This is a prompt-namespace
replay incompatibility, not a policy/month binding regression. That replay must
not be used as the promotion metric.

## Decision

```text
product router + evidence reduction freeze: complete
equivalent-evidence addendum: complete
sufficiency gate: shadow only
semantic fallback: deferred / disabled
policy and monthly binding verifier: diagnostic GO
production/generalization promotion: NO-GO pending untouched evaluation
official sealed score: unchanged at 37/64
```

## Artifacts

- `outputs/v3/diagnostics/typed_evidence_ref_sufficiency_shadow_full64_20260727.jsonl`
- `reports/v3/typed_evidence_ref_sufficiency_shadow_full64_20260727.json`
- `outputs/v3/diagnostics/typed_evidence_ref_product_router_binding_verifier_replay_v2_20260727.jsonl`
- `reports/v3/typed_evidence_ref_product_router_binding_verifier_replay_v2_20260727.json`
- `outputs/v3/diagnostics/typed_evidence_ref_requirement_evidence_reduction_binding_verifier_replay_v2_20260727.jsonl`
- `reports/v3/typed_evidence_ref_requirement_evidence_reduction_binding_verifier_replay_v2_20260727.json`
