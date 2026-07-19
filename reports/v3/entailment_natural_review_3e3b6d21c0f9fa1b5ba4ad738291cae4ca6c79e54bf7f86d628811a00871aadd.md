# DNF RAG v3 Natural Entailment Human Review Packet

## Decision

- Packet integrity: **GO**
- Human review: **PENDING**
- Natural verifier evaluation: **NO-GO**
- Production verifier: **NO-GO**
- Generator entry: **NO-GO**

## Composition

- total: 40
- annotated anchors: 16
- current hard candidates: 16
- historical/preview candidates: 8
- claim sources: {'dnf_account_policy': 6, 'dnf_event': 4, 'dnf_faq': 4, 'dnf_game_guide': 5, 'dnf_monthly_item': 6, 'dnf_notice': 4, 'dnf_seria_shop': 6, 'dnf_update': 5}

The reviewer-facing packet hides sampling strata, dev annotations, and model predictions. The sampling ledger must not be opened during primary labeling.

## Label rules

- `support`: the evidence entails every material part of the claim for the stated time scope.
- `contradiction`: the evidence explicitly conflicts with at least one material part of the claim.
- `insufficient`: the evidence neither supports nor contradicts the claim, including omission or a different item/context.

For every row, set `reviewer_type=human`, a non-placeholder `reviewer_id`, a timezone-bearing `reviewed_at`, `review_rationale`, and `needs_adjudication`. A support or contradiction label also requires an exact `decisive_excerpt` copied from `evidence_text`.

Validate a completed copy with:

`python src/v3/prepare_entailment_review.py --validate-reviewed <completed.jsonl>`

No verifier metric may be computed until validation reports `ready_for_scoring=true`.

## Artifacts

- review packet: `data/v3/evaluation/entailment_natural_review_packet_58cc8083b4e9ba3961cf2e8b536ec2312d96333d724815fb42fddf525c2d6c8b.jsonl`
- sampling ledger: `data/v3/evaluation/entailment_natural_sampling_ledger_8acf067ed912ccf91076d501f585dbed73fbf18af17ce95ba794d305e81ca551.jsonl`
- manifest: `data/v3/evaluation/entailment_natural_review_manifest_faf4afb5d3b68c5a6b95a1b2fe4a01d47906b9c28091b6d335055c81a03512c7.json`
