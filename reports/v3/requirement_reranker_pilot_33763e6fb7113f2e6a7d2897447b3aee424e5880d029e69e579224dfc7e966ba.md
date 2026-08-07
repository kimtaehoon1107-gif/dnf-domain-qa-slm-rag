# Requirement-aware BGE reranker pilot

- Decision: **NO_GO_CAUSE_ANALYSIS**
- Retrieval-bound questions: 7
- Retrieval-bound evidence groups: 13

| arm | evidence-group coverage | all-groups questions | avg selected | annotated over-selection |
|---|---:|---:|---:|---:|
| whole-question baseline | 93/96 | 73/75 | 3.621951 | 216 |
| requirement-aware | 92/96 | 73/75 | 4.487805 | 288 |

- Strict improvements: 2
- Strict regressions: 2

Gold chunk IDs were used only after scoring for exact set membership.
No semantic matcher, answerability component, training, or generation was used.
