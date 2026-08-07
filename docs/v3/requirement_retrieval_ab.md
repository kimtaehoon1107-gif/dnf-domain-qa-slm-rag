# Requirement-query retrieval A/B contract

This is a development-only A/B for the seven false-full cases attributed to
retrieval (`RETRIEVAL_MISS=6`, `CROSS_PARENT_MISS=1`). It does not promote a
retriever, router, assembler, or runtime.

## Frozen arms

- Arm A is the frozen question-query backbone and chunk-diverse assembler.
- `requirement_only` searches the unchanged BM25+BGE-M3 index once per frozen
  planner requirement using `subject + relation` and supplies only those hits
  to the unchanged chunk-diverse exact assembler.
- `question_union_requirement` unions the frozen Arm A assembler chunks with
  each requirement's hits before the same assembler.

The source, status, exposure, and temporal envelope comes directly from the
frozen runtime route for the same case. It is not inferred from returned hits and
is not widened. Evaluation `source_ids` and gold chunk/document IDs are not used
to form the query, policy, candidate pool, reranker scores, or assembler
decision. Gold acceptable chunk IDs are used only after execution to score
candidate recovery and citations.

No index is rebuilt. The planner is not re-executed. The assembler keeps
threshold `0.001`, at most three distinct chunks per requirement, non-overlap
sentence/table-row segmentation, BAAI/bge-reranker-v2-m3, and verbatim offset
slicing.

## Gate

An arm can receive a development-only adoption recommendation only if all are
true:

1. At least one of the seven retrieval-bound false-full cases becomes grounded.
2. Grounded answers remain at least 73 and no previously grounded question
   regresses.
3. New false-full cases are zero.
4. Mean selected spans and question-level non-acceptable citation count do not
   increase over Arm A.
5. Exact span validity is 100%.
6. Same-parent controls remain 7/7, reject controls 11/11, and realtime safe
   abstain controls 2/2.

The wrong-attribute cases are outside scope. The cross-parent conclusion remains
small-sample evidence.

## Evaluation limitation

The existing assembler development evaluation does not score segment candidates
for questions with no human-gold evidence groups. This A/B preserves that
behavior because answerability is outside scope. Reject/realtime counts are
therefore inherited safety controls, not evidence that runtime answer-source
classification has been solved. This limitation must remain visible in the
report and prevents runtime promotion.

All inputs and outputs are SHA-256 content-addressed. Existing inputs are hashed
before and after execution. Frozen blind data is not an input.
