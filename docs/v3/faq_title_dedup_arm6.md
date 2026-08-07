# v3.2 Arm 6 — FAQ retrieval-title deduplication

## Suitability

279 FAQ chunks contain the exact document title twice in `retrieval_text`: once from
the index-time title prefix and once at the start of `display_text`. Removing the
second retrieval-only copy is safe to test because `display_text`, chunk IDs, offsets,
documents, and citations remain unchanged.

## Contract and gate

- Only the redundant leading title copy in FAQ `retrieval_text` may be removed.
- Non-FAQ rows and every non-retrieval field must be byte-equivalent as canonical JSON.
- FAQ BM25 top-10 evidence-group recall must improve with zero strict regression.
- A result that merely shortens text without retrieval improvement is NO-GO and is not adopted.
- The dirty canonical corpus remains unchanged; this arm is development-only.
