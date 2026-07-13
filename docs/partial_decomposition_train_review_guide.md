# Partial Decomposition Training Review

Review `data/review/partial_decomposition_train_review_24.csv`. All 24 rows must receive a decision before they can enter training.

For each row:

- `grounded_fact_correct`: `yes` only when the proposed answer preserves the source fact and evidence;
- `unsupported_request_natural`: `yes` only when the added personal decision sounds natural with the source question;
- `targeted_abstention_correct`: `yes` only when the answer refuses that personal decision without refusing the grounded fact;
- `human_decision`: `approve`, `rewrite`, or `reject`;
- for `rewrite`, fill both `human_question` and `human_answer`;
- for `rewrite`, set the three quality fields against the final human-written question and answer; accepted rows require all three to be `yes`;
- use `review_notes` for the reason or correction.

Do not change `candidate_id`, source IDs, evidence, or chunk IDs. This review is for training data only and does not modify the frozen human Partial dev set.

After all 24 decisions are complete, `src/freeze_partial_decomposition_review.py` freezes only approved or rewritten rows. It rejects incomplete reviews, edited source/evidence fields, duplicate train/eval questions, held-out parent or chunk overlap, generic refusal text, and evidence spans that are not visible in the expected chunk.
