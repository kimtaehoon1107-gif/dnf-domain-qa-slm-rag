# DNF RAG v3 Entailment Adjudication Setup

## Decision

- Primary review: **GO** (40/40)
- Pending adjudication: **9**
- Natural Verifier evaluation: **NO-GO**
- Generator entry: **NO-GO**

The completed primary draft was frozen without modification. Only rows explicitly marked `needs_adjudication=true` were copied into the separate reviewer packet. The packet contains the primary decision for context but starts with empty adjudication review fields. No model prediction or sampling stratum is loaded.

Run:

`python src/v3/review_entailment_app.py --packet data/v3/evaluation/entailment_natural_adjudication_packet_8931eb56e023bd956826692f5e86622aa2e6bdd3399ccf8be5da1bea302e301f.jsonl --draft outputs/v3/annotation/entailment_natural_adjudication_draft_8931eb56e023bd956826692f5e86622aa2e6bdd3399ccf8be5da1bea302e301f.jsonl`
