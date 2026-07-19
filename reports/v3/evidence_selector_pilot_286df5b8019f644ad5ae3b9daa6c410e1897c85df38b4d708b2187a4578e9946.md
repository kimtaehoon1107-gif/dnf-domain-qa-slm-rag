# DNF RAG v3 Answerability / Evidence Selector Pilot

## Decision

- Answerability dev baseline: **GO**
- Selector compression candidate: **GO**
- Production evidence selector: **NO-GO**
- Generator entry: **NO-GO**
- Final benchmark: **NO-GO**

## Answerability

- exact dev accuracy: 1.0
- unsupported abstention: 1.0
- answerable false rejection: 0.0
- false rows with selected evidence: 0

This is a deterministic dev-fit safety baseline, not an independent generalization result. Answerability accuracy is not interpreted without the evidence metrics below.

## Evidence selector

- candidate top-10 all-groups hit: 0.981818
- selected all-groups hit: 0.981818
- candidate top-10 group recall micro: 0.983051
- selected group recall micro: 0.983051
- average selected chunks: 8.127273
- candidate reduction: 0.187273
- annotated evidence precision: 0.129754
- annotated noise rate: 0.870246

The selector preserves the frozen top-10 evidence recall while reducing the candidate set. Its sparse-annotation precision is too low for production or generator promotion, and semantic contradiction has not been measured.

## Artifacts

- results: `data/v3/evidence/evidence_selector_pilot_results_c5f0f49ae0e519a8533d7672ba72208a73169c14263a3d77e70768ff6bef31e2.jsonl`
- manifest: `data/v3/evidence/evidence_selector_pilot_manifest_268a6e48243f6a21a5f36706692186af1a3081799d5b6f72de98948fe3fda16b.json`
