# Routing bottleneck diagnostic contract

## Purpose

This cycle diagnoses the downgraded 32-question authored canary without
changing routing, planner, retrieval, reranking, assembly, answerability, or
labels. It uses only already-frozen, previously inspected attribution and
text-free diagnostic artifacts. No question or gold text is copied into the
new artifacts.

The apparent routing bottleneck has two denominators which must not be mixed:

- 14/32 questions first fail at routing;
- 23/50 evidence groups first fail at routing, but all 23 belong to the nine
  evidence-bearing questions labelled `expected_route=decompose`.

The five `reject`/`realtime_api` controls have no required evidence groups, so
they are absent from the 50-group denominator. Tractable versus parked is
therefore reported primarily over the 14 failed questions. The 23 groups are
reported separately as same-parent versus cross-parent.

## Exclusive taxonomy

Each of the 14 routing-failed questions receives exactly one type:

- `DECOMPOSE_MISS`: expected decompose and the frozen parent diagnostic says
  no single parent covers every evidence group;
- `REALTIME_MISS`: expected realtime API;
- `REJECT_MISS`: expected reject;
- `LABEL_SUSPECT`: expected decompose but one parent covers every evidence
  group, so the planner plus same-parent assembler is the appropriate path.

`LABEL_SUSPECT` is an audit finding only. The frozen canary and its gold labels
are not edited.

## Planner counterfactual

The frozen enumeration artifact is joined by case ID. The diagnostic only
counts the hypothesis `requirement_count >= 2 -> multi-field path`. It does not
execute or modify a route. In particular, a multi-field signal on a reject or
realtime control is counted as a safety conflict, not a success.

The report must distinguish:

- structurally planner-path questions: same-parent multi-field plus genuine
  cross-parent decomposition;
- immediately detected tractable questions under the frozen planner output;
- parked answerability questions;
- the genuine cross-parent planner miss.

## Scope

No router rule, keyword, model, prompt, label, question, gold, or runtime
artifact may be changed. The downgraded canary remains adaptive validation and
is not a sealed benchmark. No new canary is run. Passing this diagnostic only
selects the next approach; it cannot promote a runtime or canonical component.
