# Router backbone and answer-source A/B contract

## Purpose

This development-only A/B composes already-frozen planner, requirement
reranker, and mechanical extractive assembler artifacts. It compares a common
groundedness backbone (`Arm0`) with the same backbone plus the frozen
deterministic `qwen3:8b` answer-source classifier (`Arm1`). Nothing in this
cycle is promoted to canonical or runtime, and no sealed evaluation is run.

The classifier output already covers all 95 frozen questions at temperature
zero. Reusing that content-addressed output makes the front-versus-post-search
comparison deterministic and avoids a new model run. The model tag, model SHA,
prompt SHA, and original latency remain part of the lineage.

## Narrow safety pre-gate

Both arms reuse only existing reason codes for protected-instruction attacks,
unsafe abuse instructions, and obvious lottery, financial-market, or weather
OOD requests. No new regular expression or keyword is added. Existing
private-account, realtime-auction, subjective, and advice classifications are
explicitly ignored by this pre-gate.

## Arm0: groundedness-only backbone

After the narrow safety pre-gate, the frozen planner is considered always on.
For each requirement, the final mechanical chunk-diverse assembler supplies
either `supported_exact` spans or `unsupported`:

- all supported: full extractive answer;
- some supported: partial answer with unsupported requirements disclosed;
- none supported: abstain;
- multiple supported requirements with no shared cited parent: cross-parent
  decomposition candidate.

The parent test uses only the parents of requirement-specific cited spans. It
does not use all retrieval candidates or gold IDs.

`supported_exact` guarantees verbatim extraction, not semantic entailment.
Human-gold acceptable chunk IDs are therefore used after the decision solely
to measure grounded full answers, honest partial answers, and false full
answers. They never affect an arm's runtime decision.

## Arm1: frozen semantic answer-source classifier

The frozen requirement-level classes are normalized to:

- `official_docs`: allow document evidence;
- `personal_account` or `realtime`: route to `realtime_api` when no document
  answer remains;
- `subjective` or `out_of_scope`: reject when no document answer remains;
- `ambiguous`: abstain when no document answer remains.

Two placements are evaluated:

- `front`: answer-source classification controls whether an otherwise
  supported requirement may enter the backbone;
- `post_search_evidence_priority`: supported evidence is preserved and the
  classifier acts only on unsupported requirements.

Question-level over-rejection, expected-document requirement suppression, and
grounded-answer regression are all hard safety measurements. A partial answer
does not hide suppression of an expected document requirement.

## Frozen decision rule

Arm1 is recommended only if one placement simultaneously:

1. increases honest-correct total over Arm0;
2. does not increase answerable-question over-rejection;
3. suppresses zero additional expected-document requirements;
4. does not reduce grounded answer success or reject correctness.

Realtime preferred routing is reported separately because its denominator is
two. Safe abstention and realtime routing are both non-exposure outcomes, but
only routing counts as the preferred realtime action.

The backbone is compared with the frozen 32/32-retrieve canary router using
both original route labels and the prior text-free seven-row same-parent label
audit. Labels are not edited. A development-backbone GO does not imply runtime
GO; false-full answers and cross-parent trigger failures remain blockers.

## Scope

No new classifier, prompt, keyword list, training, retrieval, reranking,
assembler, question, gold, or label change is allowed. Frozen blind, v2,
`AGENTS.md`, the v3 handoff, `src/outputs`, and raw data are out of scope.

