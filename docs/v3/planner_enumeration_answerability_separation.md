# Planner enumeration / answerability separation contract

## Decision fixed before A/B output

The semantic requirement planner is an enumeration-only component. Its frozen
prompt SHA-256 is
`01ddcf34498276b4896f5c628f53fa874047e8a989b3a5df3e405bd43c87d948`.
The directional strong-rematching result supplied for this cycle is about 90%
requirement recall on the downgraded 32-set and about 98% on adaptive dev 63.
That result marks enumeration GO and is not re-created from the rejected 4B
gold/matcher artifacts here.

The canonical enumeration projection contains only requirement identity plus
`subject`, `relation`, `value_type`, and `subject_group`. Legacy
`answerable_from_docs` values and optional planner fields are omitted. They do
not participate in planner acceptance, reranker input acceptance, or promotion.

## Separate answerability component

Input is the original question plus the frozen atomic requirements. Output per
requirement is exactly one of:

- `official_docs`
- `personal_account`
- `realtime`
- `subjective`
- `out_of_scope`
- `ambiguous`

Approach A is the strongest already-installed fixed local classifier
(`qwen3:8b`) with temperature 0 and a content-hashed multiclass prompt.
Approach B is a deterministic structural marker gate using the predeclared
ownership-plus-personal-target, realtime, subjective, and out-of-scope marker
families. It is not part of the planner or reranker.

Both arms use the already frozen independent 95-question answerability ground
truth. It was frozen before this A/B run and is not the rejected 4B gold. An
`official_docs` decision on a ground-truth non-document requirement is a docs
false positive. A clear non-document class on a document requirement is a docs
false negative. `ambiguous` is counted separately and sent to independent human
or strong-judge adjudication; it is not silently converted to either boolean.

## Precommitted A/B selection

An arm qualifies only when clear-case docs false positives are zero and clear
coverage is at least 80%, preventing a trivial all-ambiguous solution. Among
qualified arms choose the fewest docs false negatives, then the fewest ambiguous
requirements. Any selected arm with ambiguity remains a development candidate
pending independent adjudication. This cycle does not promote either arm to the
runtime or canonical pipeline.

Planner enumeration GO independently unblocks the next requirement-aware
reranker pilot. Answerability is needed later for answer assembly, partial, and
reject behavior, so an answerability A/B failure cannot retroactively block the
enumeration planner.

## Scope

No reranker, entailment judge, answer generator, training, free-form generation,
or new canary is added in this cycle. No individual evaluation question is used
to tune either arm after its output is observed.
