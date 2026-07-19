# DNF RAG v3 Natural Entailment Review Contract

## Purpose

The controlled NLI pilot does not measure naturally occurring claim/evidence
relationships. This review packet is the required human-labeling bridge before a
Verifier can be evaluated on official DNF text outside synthetic counterfactuals.

It is a stratified challenge set, not an estimate of production class prevalence.
It must not be used for training or called a final benchmark.

## Frozen sample

The 40 claims are unchanged `gold_answer` text from the retrieval development set.
Their evidence comes from immutable ChunkV3 rows:

- 16 annotated anchors: two per official source;
- 16 current hard candidates: the highest semantic-reranker candidate outside the
  annotated acceptable chunk IDs, two per source;
- 8 historical/preview candidates: same-source BM25 matches from superseded,
  expired, or preview-safe non-default documents.

The reviewer-facing packet is sorted by a content-derived item ID and omits the
sampling stratum, dev annotation relationship, and all model predictions. The
separate sampling ledger is provenance for later analysis and should remain closed
during primary labeling.

## Human labels

- `support`: the evidence entails every material part of the claim for the stated
  time scope.
- `contradiction`: the evidence explicitly conflicts with at least one material
  part of the claim. Mere omission is not contradiction.
- `insufficient`: the evidence neither supports nor contradicts the claim, such as
  a different item, context, or missing fact.

Every completed row must preserve all non-review fields and provide:

- `review_label`;
- `reviewer_type` equal to `human` and a non-placeholder `reviewer_id`;
- timezone-bearing `reviewed_at`;
- a substantive `review_rationale`;
- boolean `needs_adjudication`;
- for support or contradiction, an exact `decisive_excerpt` copied from the
  evidence text.

Validate a completed content-addressed copy with:

```powershell
python src/v3/prepare_entailment_review.py --validate-reviewed <completed.jsonl>
```

Scoring remains blocked unless validation reports `ready_for_scoring=true`, no row
needs adjudication, and all three labels are represented.

## Local review UI

Launch the reviewer-only interface from the repository root:

```powershell
python src/v3/review_entailment_app.py
```

It binds to `127.0.0.1:7861` and does not create a public share link by default.
The frozen packet remains read-only. Each save atomically updates a mutable draft
under `outputs/v3/annotation`; the immutable export button is blocked until the
validator accepts all 40 rows and no adjudication remains. The UI never loads the
sampling ledger or model predictions.

If an item does not meet a save condition, its form values are preserved and the
exact validation reason appears below the buttons; no draft write or navigation
occurs.

## Current gate

- packet integrity: GO
- human review: PENDING
- natural Verifier evaluation: NO-GO
- production Verifier and Generator entry: NO-GO
