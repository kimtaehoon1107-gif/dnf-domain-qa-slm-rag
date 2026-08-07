# False-full nine-case audit contract

## Scope

This development-only audit classifies the nine false-full answers produced by
the frozen Arm0 router backbone. It changes no question, gold evidence group,
label, planner output, retrieval result, verifier, router, or assembler. It does
not promote runtime code or run a model or sealed benchmark.

Each case receives exactly one primary type:

- `A_WRONG_ATTRIBUTE`: the needed evidence is in the candidate pool, but the
  exact citation answers an adjacent attribute or wrong entity.
- `B_RETRIEVAL_MISS`: at least one decisive acceptable evidence group is absent
  from the frozen search candidates, after excluding a known cross-parent case.
- `C_MEASUREMENT_ARTIFACT`: the cited evidence directly supports the requested
  subject and attribute but is omitted by the question-level acceptable-chunk
  list.
- `D_CROSS_PARENT_MISS`: the question requires evidence from distinct parents
  and the frozen route treats incomplete evidence as a full answer.

The precedence is `D`, then `B`, then `A`, then `C`, because this audit attributes
the earliest or structurally dominant cause. Secondary observations remain in
the rationale and do not create a second primary type.

Severity is either `catchable` when reading the citation exposes the mismatch
directly, or `subtle` when a plausible date, value, or nearby fact can mislead a
reader. Form is either `wrong_value_presented` or
`unsupported_requirement_marked_full`.

The case classifications are explicit human audit judgments over frozen inputs,
not runtime rules. Gold IDs are used only for diagnosis.

