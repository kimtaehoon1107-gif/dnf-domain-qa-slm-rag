# DNF RAG v3 Resolved Natural Entailment Reviews

## Decision

- Claim repair human review: **GO**
- Resolved 40-row integrity: **GO**
- Evidence-error exclusions: **GO**
- Three-class natural Verifier evaluation: **NO-GO**
- Contradiction supplement: **REQUIRED**
- Generator / final benchmark: **NO-GO**

## Final review view

- resolved rows: 40
- evaluation-eligible rows: 38
- excluded evidence-provenance rows: 2
- labels before exclusion: {"insufficient": 23, "support": 17}
- eligible labels: {"insufficient": 21, "support": 17}

Four claim relationships now use content-addressed corrected revisions. Two human-confirmed parent/body provenance errors remain preserved in the resolved artifact but are excluded from the evaluation view. No contradiction is present, so three-class scoring remains blocked and a separate naturally mined contradiction supplement requires blind human review.
