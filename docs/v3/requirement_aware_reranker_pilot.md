# Requirement-aware reranker pilot contract

## Frozen hypothesis and inputs

The clean 95-case enumeration artifact
`semantic_requirement_enumeration_495caba...jsonl` supplies only atomic
`subject`, `relation`, `value_type`, and `subject_group`. Answerability is parked.
The existing 32-case downgraded canary and 63-case adaptive dev human evidence
groups are scoring gold. The rejected 4B requirement overlay is not used.

The BM25+BGE-M3 candidate sets are frozen inputs and are not regenerated or
changed. Gold chunk IDs are unavailable to the reranker and are used only after
scoring for exact set membership.

## A/B fixed before model output

Both arms reuse `BAAI/bge-reranker-v2-m3` revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, max length 512, and the existing
adaptive selector: top 3 normally and top 8 for the already-established
multi-evidence or low-confidence conditions.

- Baseline: rerank each frozen candidate set once with the whole question and
  apply the current adaptive 3/8 selector.
- Requirement-aware: for every frozen requirement, rerank the same candidates
  using exactly `subject + relation`, apply the same selector independently,
  then take the deterministic union of selected chunk IDs.

No per-question top-k, query wording, keyword, or threshold tuning is allowed.
The union may select more chunks; annotated over-selection and average selection
count are therefore mandatory measurements.

## Mechanical scoring and gate

An evidence group is candidate-bound when at least one human-approved
`acceptable_chunk_id` occurs in the frozen candidate set. Other groups and any
question containing one are reported as retrieval-bound and excluded from the
reranker promotion gate.

Primary metrics on the candidate-bound subset are:

- per-evidence-group exact chunk-ID coverage;
- all-evidence-groups-covered question count and rate;
- strict question improvements and regressions versus the whole-question arm;
- annotated over-selection, average selected count, and latency.

GO requires a strict increase in all-groups-covered questions and zero strict
question regressions. Otherwise the pilot is NO-GO and failures are divided into
candidate shortage versus candidate-present ranking/requirement-expression or
selection-depth failures. No semantic matcher is involved.

## Scope

This is a development-only reranker pilot. It adds no retrieval change,
answerability logic, entailment judge, answer generator, training, new keyword
rules, or new canary. A GO permits the next entailment/answer-assembly pilot but
does not itself promote a runtime or canonical selector.
