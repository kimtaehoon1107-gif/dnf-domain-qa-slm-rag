# Corpus hygiene NO-GO diagnostic

## Result

- Grounded: 73/82 -> 72/82
- False full: 9/82 -> 10/82
- New regression: `retrieval_dev_sha256_64d1cca28aa1cff2106d80948722fd600fc754bc741f900c508878fa8dcc68b6`; unchanged gold moved from rank 10 to 20 (outside top 10).
- P1 navigation cases resolved: 1/3; 2 remain because the assembler segments preserved `display_text`.
- Exact invalid spans: 0; federated temporal violations: 0

The clean corpus is not promoted. Removing boilerplate from retrieval_text alone is insufficient while citation segmentation still consumes unchanged display_text.
