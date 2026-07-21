# Exact-extractive Answer Assembler pilot contract

## Fixed inputs and boundary

This pilot uses the clean 95-case requirement enumeration, the unchanged
whole-question baseline selected evidence, and the frozen per-requirement BGE
scores only to order chunks inside that selected set. The NO-GO
requirement-aware union is not promoted. Retrieval, reranking, planner output,
entailment, and answerability are unchanged or parked.

The local fixed model proposes, for each requirement, one selected chunk ID and
one continuous verbatim span, or `unsupported`. A deterministic cutter accepts
the proposal only when the chunk was supplied and Python exact substring lookup
succeeds. It then emits the original slice and character offsets. No fuzzy
repair, normalization, paraphrase, concatenation, or free-form answer is allowed.

## Mechanical scoring

Human-approved evidence groups from the downgraded 32-set and adaptive dev 63
are scoring-only. Gold IDs and evidence spans are absent from model input.

The canonical `47/59` is an evidence-group micro count, not a question rate.
Therefore this pilot reports separately:

- direct dev evidence-group citation coverage versus raw `47/59`;
- evidence-group coverage on groups whose acceptable chunk is present in the
  frozen selected evidence;
- all-gold-groups-cited question rate;
- descriptive per-planner-requirement exact-span and gold-chunk citation rates.

No semantic requirement-to-group matcher is introduced. A group is cited when
at least one accepted exact span cites one of its acceptable chunk IDs. The gold
evidence span is additionally checked by whitespace-normalized containment and
reported, but it is not silently substituted for model output.

Upstream-bound questions, where selected evidence lacks at least one acceptable
chunk, are separated from assembler failures and split into retrieval-bound
(acceptable evidence absent from candidates) and selection-bound (present in
candidates but absent from selected evidence). Within eligible questions,
unsupported, invalid span, and valid-span/wrong-chunk failures are counted.

## Gate fixed before output

GO requires all of the following:

- adaptive-dev evidence-group hits exceed the canonical 47;
- combined all-groups-cited question count improves;
- evidence-group and question strict regressions are both zero;
- proposed supported spans rejected as non-substrings are zero.

The raw dev denominator remains 59 for continuity; the one known upstream-bound
group is excluded only from the assembler gate denominator. Individual question
or span tuning is prohibited.

## Scope

This is a development-only exact-extractive assembler pilot. It performs no
training, entailment judgment, answerability decision, free-form generation,
keyword expansion, retrieval/reranker/planner modification, or new canary run.
