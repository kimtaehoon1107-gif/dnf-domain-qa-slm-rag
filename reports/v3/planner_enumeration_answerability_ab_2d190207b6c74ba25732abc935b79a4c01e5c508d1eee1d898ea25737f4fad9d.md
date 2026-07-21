# Planner enumeration / answerability separation

- Planner enumeration: **GO** (user-confirmed strong rematching; not rerun here)
- Answerability decision: **NO_GO_ANSWERABILITY_AB**
- Selected approach: `None`

## A/B metrics

### approach_a_fixed_model

- docs false positive: 2
- docs false negative: 24
- ambiguous: 0
- clear coverage: 1.0

### approach_b_structural_gate

- docs false positive: 3
- docs false negative: 5
- ambiguous: 30
- clear coverage: 0.805195

Ambiguous rows remain an adjudication queue and are not silently
converted to official_docs. No answerability arm is promoted to runtime
by this development-only A/B evaluation.
