# Corpus retrieval hygiene contract

## Scope

This cycle removes measured navigation, footer, and policy revision-selector text from `ChunkV3.retrieval_text` only. It does not change the search model, planner, reranker, assembler, gold labels, questions, or canonical runtime.

The dirty corpus and every prior result remain immutable. The clean corpus is a separate content-addressed development artifact and is not promoted by this cycle.

## Allowed transformations

- Remove a trailing `텍스트복사` + `목록` footer and everything after it.
- Remove the known anti-phishing banner alt immediately before that footer.
- For policy documents, remove the revision-date selector and duplicated table of contents while retaining the repeated first heading that begins the actual policy body.
- Record cross-source event/shop/monthly parents with the same normalized title as duplicate-parent candidates. Do not merge them automatically.

No table row, price, period, deletion date, trade type, or substantive body text may be removed. A row that would become empty is a hard failure; the current corpus contains no pure-navigation-only row, so no chunk is excluded.

## Identity and citation invariants

For every chunk, all fields other than `retrieval_text` must remain identical. In particular:

- `chunk_id`, `parent_document_id`
- `display_text`
- `start_offset`, `end_offset`
- `normalized_text_hash`, `parent_content_hash`
- temporal and exposure metadata

Gold acceptable IDs are not edited or remapped because chunk identity does not change. Every evidence span that was an exact substring before cleaning must remain exact after cleaning. Pre-existing non-exact legacy spans are reported separately and may not increase.

## Blast-radius rule

Changing `retrieval_text` invalidates both lexical and dense indexes. A clean-corpus result is interpretable only after:

1. rebuilding BM25 with the same tokenizer and parameters;
2. rebuilding BGE-M3 with the same model revision and encoding parameters;
3. replaying the 63 adaptive-dev and 32 downgraded-canary candidate paths;
4. replaying the frozen planner, requirement reranker, chunk-diverse exact assembler, and groundedness backbone;
5. rechecking the P1 federated navigation-contamination cases and temporal safety.

Promotion remains out of scope. Any drop below the dirty grounded 73/82 baseline, new false-full answer, non-exact citation, or temporal/safety leak produces `NO-GO`.
