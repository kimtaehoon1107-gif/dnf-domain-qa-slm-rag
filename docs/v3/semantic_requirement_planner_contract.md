# Semantic Requirement Planner evaluation contract

## Scope

This cycle evaluates only `question -> atomic requirements`. It does not change
retrieval, evidence selection, reranking, temporal verification, or answer
generation. Planner output is development-only and cannot be promoted to the
runtime or canonical pipeline by this evaluation.

Each requirement has `subject`, `relation`, `value_type`, `subject_group`, and
`answerable_from_docs`. Optional `qualifiers`, `time_scope`, and
`coordination_scope` are emitted only when their omission would change what must
be answered. One output object must represent exactly one requested fact.

## Frozen population

- Primary population: the 32-row downgraded authored canary plus the 63-row
  adaptive development set, 95 unique questions total.
- Stress slice: the 15-row claim-ceiling set. All 15 rows are already contained
  in the downgraded 32-row set, so they are reported separately and never added
  again to a primary numerator or denominator.
- No frozen blind, v2 artifact, raw snapshot, `AGENTS.md`, handoff, or
  `src/outputs` is an input.

## Independence and freeze order

1. Gold author B receives the question and evidence-group hints only. The
   question is authoritative; evidence may resolve ambiguity but may not add a
   requirement the question did not ask for.
2. The Gold Requirement Overlay is content-addressed and frozen before Planner A
   is invoked. Planner output is never included in the gold prompt.
3. Planner A receives only the question. It does not receive gold requirements,
   evidence spans, chunk IDs, source IDs, answerability labels, or retrieval
   output.
4. Matcher C receives the frozen gold requirements and planner requirements. It
   does not author either side.
5. Human adjudication is a separate overlay. The frozen authored gold, planner,
   and matcher artifacts are never rewritten.

Gold author B, Planner A, and Matcher C must use different fixed model tags and
different prompt hashes. Model tag, model digest, Ollama version, OpenAI SDK
version, temperature, and latency are recorded. Temperature is fixed at zero.

## Semantic matching

Matcher verdicts are `MATCH`, `PARTIAL_MATCH`, `NO_MATCH`, or `AMBIGUOUS`.
Only `MATCH` counts as correct in primary metrics. Matching must preserve subject,
relation, compatible value type, subject-group attribution, material qualifiers,
and answerable-source compatibility.

Scoring uses a maximum one-to-one bipartite matching over `MATCH` edges. One
prediction can match at most one gold requirement and one gold requirement can
match at most one prediction. Lexical overlap, morphology overlap, or embedding
cosine alone is never the final match decision.

If the local matcher violates the Cartesian-pair output protocol, an omitted pair
is conservatively recorded as `NO_MATCH`, the omission count is reported, and the
question is forced into human review. Such normalization cannot independently
support a final GO.

## Human review

The review packet includes:

- every `AMBIGUOUS` or `PARTIAL_MATCH` case and every automatic mismatch;
- 100% of multi-requirement, mixed-source, realtime, and personal questions;
- a deterministic 20% sample of remaining simple single-requirement questions.

Until this packet is completed by the named human reviewer, matcher metrics are
provisional. `judge_false_match`, `judge_false_nonmatch`, judge-human agreement,
and final GO/NO-GO remain pending; an agent may not impersonate that reviewer.

## Metrics and precommitted gates

All rates are reported with integer numerators and denominators.

- micro requirement recall: at least `0.90`;
- micro requirement precision: at least `0.85`;
- over-enumerated question rate: at most `0.10`;
- `answerable_from_docs` false positives: exactly `0`;
- all-requirements-recalled question rate: at least `0.85`.

Required slices are source, single versus multi-requirement, docs versus
realtime/personal/mixed, and the 15-row claim-ceiling stress slice. Reports also
include ambiguous count, human-review planned/completed counts, matcher-human
agreement when available, latency, docs false negatives, and the prior Signal A
figures as contextual baselines.

Passing these gates means only `GO_TO_RERANKER_PILOT`. It does not promote the
planner to runtime or canonical use. Before human adjudication is complete the
only valid decision is `PENDING_HUMAN_ADJUDICATION`, even if provisional model
metrics pass.
