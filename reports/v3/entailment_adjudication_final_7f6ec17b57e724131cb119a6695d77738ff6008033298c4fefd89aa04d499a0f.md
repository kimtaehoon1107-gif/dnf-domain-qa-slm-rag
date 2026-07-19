# DNF RAG v3 Entailment Adjudication Finalization

## Decision

- 15-row human adjudication: **GO**
- Merge into the primary 40 rows: **NO-GO**
- Claim repair review: **PENDING**
- Evidence parser repair: **REQUIRED**
- Natural Verifier / Generator: **NO-GO**

## Human labels

- support: 5
- contradiction: 0
- insufficient: 10

The human review identified 4 claim-error relationships across 2 unique claims and 2 evidence-provenance errors. The original rows remain immutable. Corrected claim revisions must be reviewed on the same 4 relationships before merge. Evidence-error rows remain excluded until parser/chunk provenance is rebuilt.

Run:

`python src/v3/review_entailment_app.py --packet data/v3/evaluation/entailment_claim_repair_packet_4ab7ded1cc83ea7c1ffa658874ae2f5f2e6b642f321988dc73f789e018ed1a2b.jsonl --draft outputs/v3/annotation/entailment_claim_repair_draft_4ab7ded1cc83ea7c1ffa658874ae2f5f2e6b642f321988dc73f789e018ed1a2b.jsonl`
