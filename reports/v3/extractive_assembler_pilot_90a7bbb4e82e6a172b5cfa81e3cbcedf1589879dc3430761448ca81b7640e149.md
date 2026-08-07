# Exact-extractive Answer Assembler pilot

- Decision: **NO_GO_CAUSE_ANALYSIS**
- Dev direct group comparison: 47/59 baseline -> 34/59 assembler
- Dev selected-input subset: 34/58
- Combined all-groups questions: 59/73 -> 47/73
- Span validity: 95/135
- Evidence-group improvements/regressions: 8/30
- Upstream exclusions: retrieval 7 questions/13 groups; selection 2 questions/3 groups

The canonical 47/59 value is an evidence-group micro metric, not a
question rate. Both units are reported separately. Gold IDs and spans
were absent from model input and used only for deterministic scoring.
