# Requirement entity-anchor A/B contract

## Purpose

Development-only correction for planner subjects that truncate an official
entity name. The motivating case is `광휘의 행로` becoming `광휘`, which lets
unrelated siblings such as `광휘의 잔영` compete while the correct guide and
update sentences are rejected by the structural support certificate.

## Arm definition

Arm 0 is the frozen contextual answer-unit v3.2.5 result.

Arm 1 keeps the frozen planner requirement count, relation, value type, route,
retrieval indexes, rerankers, assembler thresholds, and corpus. Before
requirement-level reranking it may expand only the requirement `subject`:

1. build a deterministic index from current official DocumentV3 titles and
   ChunkV3 `heading_path` values;
2. keep only official phrases that occur as an exact substring of the original
   question and strictly contain the planner subject;
3. select the longest phrase, breaking ties lexicographically;
4. preserve the original as `planner_subject` and record entity provenance.

There is no fuzzy match, global particle stripping, domain keyword list, model
call, training, reindexing, or gold access. A question that says only `광휘`
does not authorize either `광휘의 행로` or `광휘의 잔영`.

## Evidence adjudication

The existing authored question has only the update chunk in its acceptable
group. The current guide page contains the same two exact evidence spans. The
guide chunk is therefore reported as an `EQUIVALENT_OFFICIAL` sibling proposal,
not silently applied. Original strict and provisional adjudicated metrics remain
separate until human acceptance.

## Pre-registered gates

- the guide candidate cites both exact values: `58,950` and `한 번에 하나`;
- `광휘의 잔영` is not cited for either requirement;
- frozen docs 69 has zero previously passing question regression;
- authored adaptive 24 has zero previously passing question regression;
- Quick-account-transfer four exact evidence spans remain covered;
- no new false-full under original strict scoring;
- exact citation remains 100%;
- temporal/revision/preview leakage remains zero;
- no runtime or canonical promotion.

Passing means only `DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED`.
