# Lightweight semantic-support verifier A/B

## Status and scope

This is a development-only A/B over the frozen 95-question population. It adds a
pairwise verifier after the exact-extractive assembler and does not promote any
component into canonical or runtime code. It does not run a sealed canary, train a
model, change retrieval, or change the planner, reranker, or assembler.

The verifier question is narrowly defined: does a selected verbatim span actually
answer its paired atomic requirement? Verbatim extraction alone is not treated as
support.

## Frozen arms

- `bge_support_pair`: frozen `BAAI/bge-reranker-v2-m3` scores a support-oriented
  requirement query against each selected span. This is a calibrated relevance
  proxy, not entailment.
- `mdeberta_nli_support`: frozen
  `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` scores the span as premise and an
  atomic requirement-plus-extracted-value statement as hypothesis. This is a
  dedicated NLI component, not a general LLM yes/no prompt.

Gold chunk/document/source IDs are unavailable to both arms. Human-reviewed
acceptable chunk IDs are attached only after inference for mechanical scoring.

## Predeclared grid and gate

BGE bars are `0, .001, .005, .01, .02, .05, .1, .2, .3, .5, .7, .8, .9,
.95, .99`. NLI entailment-probability bars are `0, .01, .05, .1, .2, .3,
.5, .7, .8, .9, .95, .99`.

The hard preservation checks at an operating point are:

- grounded answer count remains exactly `73`;
- reject controls remain `11/11` correct;
- realtime controls remain `2/2` safe-abstain with zero static exposure.

Adoption additionally requires at least two of the nine false-full answers to be
removed. That is the predeclared minimum meaningful reduction for this small dev
sample. Cross-parent triggering is reported but remains descriptive because
`n=2`.

Among passing bars, selection minimizes false-full count, then maximizes
cross-parent triggers and pairwise recall, then chooses the lower bar. If no bar
passes all checks, the verifier is `NO-GO`; a lower grounded count is never traded
for fewer false-full answers.

## Metric limits

Primary metrics are question-level and use the original human evidence groups.
The precision/recall curve uses a transparent scoring-only proxy: a span-pair is
positive when its chunk belongs to any acceptable evidence group for that
question. This is not a requirement-to-group annotation and can over-credit a
chunk shared by multiple requirements, so it is diagnostic rather than the
adoption gate.

The NLI hypothesis includes the extracted span as the proposed value. This makes
the input an atomic claim, but it is still a task transfer from NLI to slot
answering. Poor separation is evidence against this component, not permission to
tune individual questions.

