# DNF RAG v3 Question Decomposition pilot

## Decision

- deterministic decomposition: **GO**
- child source/time rerouting: **GO**
- child BM25 evidence pilot: **GO**
- child hybrid retrieval / merge / Generator / final benchmark: **NO-GO**

## Adaptive dev pilot

- multi-document parents: 4
- generated children: 8
- parse errors: 0
- recursive child routes: 0
- child clarification routes: 0
- empty child BM25 results: 0
- parent source coverage errors: 0
- parent time coverage errors: 0
- evidence-group hit@10: 8/8
- child evidence-group specificity errors: 0

This pilot uses only the four adaptive multi-evidence development questions. Gold
evidence IDs are used after decomposition and routing solely to audit hit coverage;
they are not inputs to the decomposition rules or child Router. Unsupported sentence
patterns fail closed instead of being split heuristically.
