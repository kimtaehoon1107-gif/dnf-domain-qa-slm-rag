# DNF RAG v3 Entailment Adjudication Setup

## Decision

- Primary review: **GO** (40/40)
- Pending adjudication or text repair: **15**
- Natural Verifier evaluation: **NO-GO**
- Generator entry: **NO-GO**

The completed primary draft was frozen without modification. Rows explicitly marked `needs_adjudication=true` and rows whose saved rationale or excerpt contains clear question-mark encoding corruption were copied into the separate reviewer packet. The packet contains the primary decision for context but starts with empty adjudication review fields. No model prediction or sampling stratum is loaded.

Run:

`python src/v3/review_entailment_app.py --packet data/v3/evaluation/entailment_natural_adjudication_packet_2c82048a7ca51177278bbd9ec8782a80afae18d2f446ab0e6d365ae62de82b31.jsonl --draft outputs/v3/annotation/entailment_natural_adjudication_draft_2c82048a7ca51177278bbd9ec8782a80afae18d2f446ab0e6d365ae62de82b31.jsonl`
