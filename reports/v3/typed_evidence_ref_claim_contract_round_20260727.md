# Typed evidence-ref claim-contract v7 round

Date: 2026-07-27

## Decision

The user's diagnosis is substantially correct. Reviewed-equivalent candidate
coverage is already high; the current bottleneck is the contract between
evidence reduction, Qwen value/ref selection, the verifier, the renderer, and
the scorer.

The generalized consistency and replay-safety changes are **GO**. Portfolio
case-study publication is **GO**. Production-default promotion and a new
untouched evaluation set remain **NO-GO**.

The official sealed one-shot remains `37/64`. No adaptive or post-hoc number
below replaces that generalization result.

## Honest metric boundaries

| Metric | Result | Meaning |
|---|---:|---|
| Official sealed one-shot | `37/64` | Only untouched generalization headline |
| Historical adaptive value score | `55/64` | Inspected development set; not promotable |
| Namespace-safe source-only value score | `55/64` | Current scorer over the stored historical verified output |
| Typed answer value complete | `48/64` | Requirement-level typed values complete |
| Typed claim + approved direct evidence | `43/64` | Value and approved evidence coordinates complete |
| Frozen-gold candidate coverage | `62/64` | Candidate contains every frozen gold unit |
| Reviewed-equivalent candidate coverage | `64/64` | Includes reviewed official equivalent units |

The source-only analysis calls neither retrieval, Qwen, nor the verifier. It
does not rebuild E-reference prompts. Its role is failure analysis, not a new
model score.

The earlier verifier-replay v9 and its derived v10 output are invalid for
reporting because the stored model calls did not contain their original
E-reference namespaces. Rebuilding the current prompt could silently map an
old `E14` to a different source span. Recorded replay now fails closed unless
the claim-contract version, SHA, and complete coordinate namespace match.

## Implemented general contracts

1. Shared value normalization

   - numbers, currency, dates, clocks, ordered time ranges, and booleans
   - `daily_reset_time -> time`
   - `maintenance_time -> time_range`
   - date-only maintenance output remains rejected
   - numeric entity boundaries prevent `110` from matching `1100`

2. Batch and qualifier protocol

   - exact fixed requirement IDs or the complete ordinal set `1..N` only
   - mixed, missing, typo, or duplicate IDs fail closed
   - question-level week/round/stage is propagated only for one requirement or
     a batch whose requirements all share the same relation
   - mixed-relation batches keep only explicit planner qualifiers

3. Evidence and claim safety

   - typed text renderer preserves the verified typed value
   - subject/relation/value must be supported within one evidence group
   - policy subject/revision/effective date and monthly record boundaries are
     bound before generation
   - strict typed citations must contain the normalized expected value inside
     the overlap with an approved evidence unit
   - one-character boundary overlap and same-chunk fallback get no direct
     evidence credit
   - direct shop/monthly weapon, aura, title, and creature sibling-type
     conflicts fail closed
   - currency ambiguity, duplicate list values, and explicit unproven
     `cardinality=all` fail closed

4. Reproducible E-reference namespace

   - each new typed call records claim-contract v7
   - every `E-ref` records `chunk_id/start_char/end_char`
   - the ordered namespace has a stable SHA-256
   - replay without an exact namespace match aborts

## Reviewed equivalent-evidence overlay

The sealed artifact is deep-copied only for diagnostic scoring. An addendum
unit is accepted only after validating sealed/corpus SHA, slot/candidate/
requirement identity, exact corpus coordinates, and document metadata.

| Overlay result | Count |
|---|---:|
| Evidence units applied to already-supported claims | `6` |
| Silent claim-target changes | `0` |
| Claim corrections held out | `2` |

Slots 31 and 47 remain separate target-correction issues because the sealed
targets mark them unsupported despite official evidence.

## Human review of source-only semantic flags

The v12 scorer emitted 14 automatic semantic flags. All 14 citations were
exact corpus slices. Human review found:

| Adjudication | Slots | Count |
|---|---|---:|
| Real product-semantic false-full | `3,30,51` | `3` |
| Official equivalent / narrow-gold false positive | `4,6,29,31,33,36,43,44,46,62,64` | `11` |

- Slot 3 used week-1 evidence for a week-5 claim; the values happened to be
  identical.
- Slot 30 returned only `115` when the complete answer was `110,115`.
- Slot 51 exposed `15 골드 코인` as the sole clone-top price although the same
  current official table contains several rows differentiated by purchase/
  trade conditions. The frozen single-value gold is itself too narrow.

## Fresh Qwen3 8B contract smoke

Four new model calls used the same stored adaptive candidate pools.

| Slot | Current result |
|---:|---|
| 3 | Correct week-5 evidence, values `4` and `12` |
| 25 | Correct `06:00` and weekly reset |
| 30 | Correct complete list `110,115` in this generation |
| 51 | Wrong sibling price selected, but verifier reduced it to partial |

Summary: correct `3/4`, actual false-full `0`, generation errors `0`, new
regressions `0`.

This is targeted adaptive evidence, not a new full-64 score. Slot 30's current
success does not close the structural risk because the frozen ClaimSpec still
omits `cardinality=all`; another generation could return a partial list.

## Stage attribution

| Stage | Current finding |
|---|---|
| Router/retrieval | Reviewed candidate coverage `64/64`; not the dominant inspected bottleneck |
| Evidence reduction | Candidate presence still does not prove a complete claim-bound group |
| Qwen selection | Multi-requirement and sibling-row selection remains unstable |
| Verifier | Blocks several wrong claims, but relation and cardinality coverage is incomplete |
| Renderer | Typed text overwrite bug is fixed |
| Scorer/gold | Equivalent evidence and target corrections must remain separate |

Candidate coverage is not the same as claim-bound evidence sufficiency.

## Remaining product blockers

- Explicit relation contracts: `22/96`
- Unvalidated relations: `74/96`, currently fail-open with an audit marker
- No general closed-group proof for list completeness
- No complete canonical subject/product/revision/qualifier ontology
- General shop records do not yet bind product, revision, sales channel, trade
  type, currency, attribute, and value as one typed identity
- Multi-requirement Qwen selection remains unstable
- Slots 31 and 47 need an explicit reviewed claim-target correction artifact

Semantic fallback remains disabled because inspected failures already contain
the needed official evidence in the candidate pools.

## Verification

- Full repository: `853 passed`, `64 subtests`
- Focused contract suite: `127 passed`, `17 subtests`
- Dependency warnings: `3`
- Fresh Qwen3 8B calls: `4`
- Fresh generation errors: `0`
- Fresh actual false-full: `0`
- New typed calls record namespace SHA and coordinates
- Sealed artifact unchanged
- `git diff --check` passed

Supporting artifacts:

- `reports/v3/typed_evidence_ref_adaptive_source_addendum_rescore_v12_20260727.json`
- `reports/v3/typed_evidence_ref_adaptive_source_semantic_adjudication_v12_20260727.json`
- `reports/v3/typed_evidence_ref_claim_contract_qwen3_8b_smoke_slots3_25_30_51_v13_20260727.json`
- `reports/v3/typed_evidence_ref_policy_month_binding_qwen3_8b_adaptive_full64_20260727.md`

## Next gate

Do not add more rules for individual sealed slots. Freeze and expand the
general relation registry, define closed-list cardinality proofs, and add a
reviewed claim-target correction policy. Only then write, human-review, and
seal a new untouched 32-question set for one A/B run.
