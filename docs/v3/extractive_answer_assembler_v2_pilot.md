# Extractive Answer Assembler v2 pilot contract

## Frozen diagnosis and design choice

The v1 frozen proposal artifact is diagnosed before v2 is run. Classification
is structural and does not use question-specific rules: exact or
whitespace-normalized text in another selected chunk is `wrong_chunk`, recovery
inside the cited chunk after whitespace normalization is `whitespace_only`, two
or more non-contiguous copied blocks with at least 85% non-whitespace coverage
is `multi_segment`, and the remainder is `paraphrase`.

The frozen v1 counts are 23 paraphrases, 9 wrong chunks, 3 whitespace-only
differences, and 1 multi-segment composition among 36 non-substring proposals.
Whitespace normalization alone can recover only 3/36, so v2 replaces generated
text with segment selection. Multiple segment IDs are allowed because a real
multi-segment case exists. The four malformed requirement outputs and six valid
span but no-gold-group selections are kept as separate failure categories.

## Segment contract

Only the unchanged whole-question baseline selected chunks are segmented.
Candidates are deterministic exact slices:

- paragraphs separated by blank lines;
- sentence units from non-table lines using kiwipiepy;
- Markdown-like table rows containing at least two pipe delimiters.

Every candidate records `span_id`, `chunk_id`, `start_char`, `end_char`, exact
`text`, and one or more structural kinds. IDs are hashes of the chunk ID,
offsets, and exact text. Duplicate offset pairs are merged. The final text is
always sliced from the frozen chunk by offsets; no copied or generated text is
accepted.

## Requirement selection

Each frozen planner requirement is evaluated independently. The local model
sees the question, one requirement, and the candidate segments ordered by the
already-frozen requirement-level chunk scores. It returns either one or more
`span_id` values or `unsupported`. It cannot return answer prose. Unknown IDs,
duplicate IDs, an empty supported selection, or a non-empty unsupported
selection are malformed outcomes, not silently repaired.

`unsupported` here means that the supplied selected evidence has no chosen
answer segment. It is not the parked personal/realtime/subjective
answerability decision.

## Mechanical scoring and upstream exclusions

Human evidence-group chunk IDs are scoring-only and never enter model input.
A group is cited when at least one selected valid segment belongs to one of its
acceptable chunks. Requirement-level gold-chunk coverage is descriptive because
there is no new semantic requirement-to-group matcher.

Retrieval-bound questions (acceptable evidence absent from candidates) and
selection-bound questions (present in candidates but absent from the frozen
selected evidence) are reported separately and excluded from the assembler
gate. Segment misselection is a downstream assembler failure.

## Gate fixed before v2 output

GO requires every condition:

- adaptive-dev evidence-group hits exceed the canonical 47/59;
- evidence-group strict regression is zero;
- fully-cited-question strict regression is zero;
- the fully-cited-question count improves;
- invalid exact-slice output is zero;
- malformed requirement output is zero.

The downgraded 32-set and adaptive dev 63 are development-only free validation.
Individual failures cannot be used to add rules or tune the prompt. A new
sealed canary is allowed only after this gate passes.

## Scope

This cycle changes only assembler output representation. It does not change
retrieval, reranking, planning, entailment, answerability, temporal policy, or
generation. It performs no training, keyword expansion, or free-form answer
generation.
