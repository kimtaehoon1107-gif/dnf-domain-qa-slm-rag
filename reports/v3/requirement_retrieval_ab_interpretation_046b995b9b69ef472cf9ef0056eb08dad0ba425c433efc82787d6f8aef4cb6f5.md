# Requirement-query retrieval A/B — final interpretation

Status: **NO-GO; no canonical/runtime promotion**  
Canonical A/B report SHA-256: `ff945c4b87b691b248ced8a3541ba53cd025f41183dd03de5dddf00ae8b45cd9`  
Canonical A/B manifest SHA-256: `40fc2122cb462f97ac930f201e817e7784c4c17a5be07485e2b244d926597788`

## Result

| arm | candidate recovery | false-full→grounded | grounded | false-full | new false-full | exact | same-parent | reject | realtime safe | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Arm A frozen | 0/7 | 0/7 | 73/82 | 9/82 | 0 | 100% | 7/7 | 11/11 | 2/2 | baseline |
| requirement-only | 0/7 | 0/7 | 63/82 | 19/82 | 12 | 100% | 7/7 | 11/11 | 2/2 | FAIL |
| question∪requirement | 0/7 | 0/7 | 64/82 | 18/82 | 11 | 100% | 7/7 | 11/11 | 2/2 | FAIL |

The seven target questions contain 13 human-gold evidence groups. Neither new
arm placed an acceptable chunk in the top-10 candidate union for any group
(`0/13`), so no false-full target became grounded.

## Earliest-stage interpretation

Post-execution scoring compared the frozen runtime route source set with each
target's human-gold chunk source:

- route source includes the gold source: `1/7`
- route source excludes the gold source: `6/7`
- the one route-aligned case still misses the gold chunk at requirement-query
  top-10: `1/1`

Therefore six cases are not repairable by changing only the query text while
the frozen route is held constant. They are route/source-envelope failures
upstream of retrieval ranking. The remaining case is a requirement-query or
index-recall miss. The earlier broad label `search-bound 7` remains useful as
candidate absence attribution, but it is not a single homogeneous retrieval
problem.

The cross-parent target was not recovered. Both new arms emitted a cross-parent
trigger in `1/2` taxonomy controls, but cross-parent grounded remained `0/2`;
triggering on distractor parents is not recovery.

## Over-selection and cost

- Arm A mean spans per supported requirement: `2.89781022`; non-acceptable
  question-level citation proxy: `174`.
- requirement-only: mean `2.85611511`, proxy `250`.
- question∪requirement: mean `2.94244604`, proxy `250`.
- Added requirement searches: `139`; retrieval median/p95 `2.126/4.697 ms`.
- requirement-only segment reranker: `24,549` pairs; question median/p95
  `1,293.922/3,996.616 ms`.
- union segment reranker: `29,233` pairs; question median/p95
  `1,387.805/4,405.664 ms`.

The retrieval calls themselves are cheap; expanding the segment candidate pool
dominates latency and increases distractor citations.

## Decision

Both configurations are rejected. They recover no target, reduce grounded
answers by 10 or 9, create 12 or 11 new false-full cases, and increase the
non-acceptable citation proxy. Exact slicing and inherited safety controls pass,
but those are insufficient.

The failed preliminary run that inferred source policy from returned candidates
is preserved under report SHA `1e0f4610787355e08342725d4fcc98f0a4eb9cb7ed9d28dcc061e6146d258cff`
and manifest SHA `b88fd25b4472eb886d96bda0a94517d1a9bdd2540bd1a427bd11f17ea7725013`.
It is superseded for final interpretation because the canonical run uses the
actual frozen runtime route.

No query, gold, label, planner output, index, assembler setting, or frozen route
was changed. Gold source/chunk IDs were used only after execution for scoring.
