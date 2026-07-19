# DNF RAG v3 Revision-conflict Review Packet

## Decision

- Packet integrity: **GO**
- Human review: **PENDING**
- Three-class natural Verifier evaluation: **NO-GO**
- Generator / final benchmark: **NO-GO**

Six exact official policy excerpts are paired with a later revision of the same
policy lineage that changed the same rule. No expected label is stored in the
packet. Human review must distinguish explicit conflict from omission.

This is a revision-conflict supplement, not a natural-distribution sample and not
a source of current-policy answers.

Run:

`python src/v3/review_entailment_app.py --packet data/v3/evaluation/entailment_revision_conflict_packet_8c2b64e9844458503e771a8a8f5d622eccdb857ae6629c4113f1c5b4e957ce4f.jsonl --draft outputs/v3/annotation/entailment_revision_conflict_draft_8c2b64e9844458503e771a8a8f5d622eccdb857ae6629c4113f1c5b4e957ce4f.jsonl`
