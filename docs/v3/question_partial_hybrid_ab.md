# Question-level partial hybrid A/B contract

## Purpose

Audit every mixed-answerability error exposed by Arm 0 and Arm Q with the frozen
question, requirement, exact span, and human evidence group. Then measure whether a
hybrid composition can remove over-claims without replacing a better current answer
with an older conservative fallback.

This is development-only. It changes no router, planner, retrieval, reranker,
assembler, corpus, gold, runtime, or canonical artifact.

## Error audit population

The audit includes the union of:

- Arm 0 `mixed_overclaim` cases;
- Arm Q `mixed_missing_evidence` cases; and
- Arm Q regressions of a previously correct mixed-partial case.

For every included case the artifact records the question, frozen human requirement
split, planner requirement, Arm 0 exact spans, human gold evidence groups, Arm Q result,
and the first observed failure stage. Gold is used only to audit and score; it is never
an Arm Q2 decision input.

## Arms

- **Arm 0**: frozen groundedness-only backbone.
- **Arm Q**: frozen question-level partial fallback A/B result.
- **Arm Q2**: use the existing question-level `partial` signal, then compose already
  frozen output in this order:
  1. preserve an Arm 0 response already marked `partial_answer`;
  2. otherwise, when a frozen claim-aware official response exists, use it;
  3. otherwise use the frozen authored-canary conservative partial response.

The order is structural, not gold-dependent. It adds no keyword, classifier, model
call, retrieval, or reranking. The adaptive-dev claim-aware artifact is the reproducible
canonical v3.1 `56/59` result; the development-only `57/59` artifact is not used.

## Scoring and strict gate

The same frozen scoring contract as Arm Q is retained. Arm Q2 is a development GO only
when all conditions hold:

1. `docs_only` chunk grounding remains at least `61/69`;
2. `docs_only` span-value grounding remains at least `45/69`;
3. mixed over-claim is `0/13`;
4. regression of the two previously correct mixed-partial questions is `0`;
5. every Q2-composed partial is exact-extractive and has the partial safety contract;
6. reject remains `11/11` and realtime safe-abstain remains `2/2`.

Passing means only that the composition is eligible for a later independent runtime
implementation and sealed evaluation. It is not runtime/canonical promotion.

## Restrictions

- No individual-question rule, keyword, model inference, training, or label change.
- No frozen blind access and no new sealed canary execution.
- No runtime/canonical promotion.
- All previous GO/NO-GO artifacts remain immutable.
