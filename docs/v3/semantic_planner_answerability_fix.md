# Semantic planner answerability-only fix contract

## Scope

This cycle changes only Planner A's `answerable_from_docs` instructions. Atomic
requirement enumeration, retrieval, reranking, evidence judgment, answer
generation, training, and runtime promotion are out of scope.

The previously reported low recall from the 4B-authored gold and matcher is not
used. The externally confirmed strong rematch result (approximately 90% on the
downgraded 32 and 98% on adaptive dev 63) is recorded as an upstream decision,
not reproduced or silently converted into a local artifact in this cycle.

## Frozen inputs and independent ground truth

The primary population remains the 95 unique questions in the downgraded 32 and
adaptive dev 63. The claim-ceiling 15 is a non-additive stress slice because it is
already contained in the 32.

Answerability truth is independent of the new planner run and follows the field's
capability meaning rather than corpus retrieval success:

- official DNF policy, product, event, update, guide, FAQ, and notice facts are
  `true`, even when the current snapshot ultimately lacks supporting evidence;
- private user/account/character state, realtime external state, subjective advice
  or prediction, and non-DNF/internal information are `false`;
- existing `answerability=partial`: a question-ordered atomic overlay is frozen
  from the pre-existing human-reviewed question and gold answer before Planner A
  is rerun.

The partial overlay is evaluation-only. It is not a runtime keyword or intent
list. The new planner output is never visible while this overlay is authored.

## Metrics and gates

- `docs_false_positive`: predicted `true` where frozen truth is `false`; hard
  gate is exactly zero.
- `docs_false_negative`: predicted `false` where frozen truth is `true`; reported
  as completeness loss.
- requirement regression: an exact ordered diff of all requirement fields except
  `answerable_from_docs` and generated requirement IDs. Hard gate is zero changed
  questions. This deliberately refuses to call a paraphrased field "unchanged"
  without a separate strong semantic matcher.
- partial rows whose predicted count does not align with the frozen overlay are
  reported as alignment limitations, not guessed into a favorable score.

`GO_TO_RERANKER_PILOT` requires both docs false positives and requirement
regressions to be zero. It does not implement or promote a reranker.

To make requirement regression structurally impossible, the original enumeration
prompt remains frozen at its prior SHA. A second Planner A boolean-only prompt sees
the question and already enumerated requirements and may change only
`answerable_from_docs`. This is a planner substage, not an evidence judge or
reranker.

## Prohibited work

No reranker, entailment judge, answer generator, training, new runtime keyword
list, frozen blind access, v2 access, raw access, or canonical promotion is part
of this cycle. Existing failed artifacts remain immutable.
