# v3.2 Arm 3 — Global temporal overlay contract

Status: development-only additive metadata A/B, not runtime/canonical-promoted.

## Purpose

Every official document receives the same temporal contract without rewriting DocumentV3. Determinate status is derived only from official effective dates, explicit validity windows, normalized status, source kind, or the previously verified policy revision lineage.

An old publication date is never sufficient to mark a document expired. Exposed FAQ, guide, notice, and live-update documents without an explicit validity end are `current_unverified`: they remain searchable with a warning, have `last_verified_at=null`, and require independent reverification before they can be called verified-current.

## Required fields

- `published_at`, `updated_at`, `valid_from`, `valid_to`
- `status`, `revision_id`, `is_current_revision`
- `supersedes_document_id`, `superseded_by`
- `snapshot_observed_at`, `last_verified_at`
- `validity_state`, `validity_reason`, `validity_evidence`
- `verified_by`, `reverify_after`, `retrieval_action_current`

`snapshot_observed_at` records fetch observation. It is not validity verification. `last_verified_at` is populated only when explicit official temporal metadata or the policy revision selector supports the determination.

## Current-mode actions

- `allow`: current policy revision or document inside an explicit active window.
- `deny`: expired, superseded, upcoming, preview, hidden, or review-required state.
- `allow_with_warning`: official exposed document whose continuing validity is not independently proven.

Historical/comparison resolution remains the existing account-policy temporal router's responsibility. Arm 3 does not introduce a broad temporal intent classifier.

## A/B gate

The overlay is retained as an additive candidate only if it covers all 980 documents, denies every determinate non-current state, fabricates zero verification dates, does not deny old notices by publication age, preserves every current-evaluation gold group and frozen current citation, and leaves normalized/chunk artifacts unchanged.
