# Contextual answer-unit selection A/B

## Role

Development-only A/B after source-isolated corrective retrieval. It does not
change the canonical corpus, index, planner, router, model weights, gold, or
labels, and it cannot promote runtime behavior.

## Diagnosis

The remaining representative failures repeatedly separate identity from value:

- a section heading names the feature while a later bullet contains the value;
- a table caption/header names the attribute while a row contains only a short
  label and number;
- a product label appears one or two value-free lines before its price.

Raw segment reranking therefore prefers a heading with query words over the
answer-bearing value line. This is the same context-loss class described by
Contextual Retrieval and late chunking, but this arm stays cheaper and fully
extractive: it contextualizes the reranker input without changing the cited
text or rebuilding embeddings.

## Arm definition

Arm 0 is the frozen source-isolated corrective result.

Arm 1 uses exactly the same per-source candidate pools and frozen BGE reranker.
For each exact non-overlapping segment it builds a retrieval-only representation
from:

1. official document title;
2. canonical chunk `heading_path`;
3. the nearest active inline section heading;
4. for table rows, the nearest preceding table header;
5. at most two immediately preceding value-free noun-phrase labels.

Adjacent lines containing a detected date, amount, duration, count, percentage,
or other answer value are never copied into the context. Any preceding line or
table row containing a digit is also excluded, even when a bare table number is
not recognized by the value-shape detector. Sentence-like lines, bullets, and
lines ending in sentence punctuation are also excluded; local context is
limited to short labels, not neighboring claims. This prevents a value or
assertion from one sibling unit being attributed to another. The final citation
remains only the original segment's `start_char:end_char` exact slice.

Compact amount-table duration labels are normalized only in the reranker view:
for example, `1월(만원)` becomes `1개월(만원)`. This is a generic Korean unit
normalization, not a question or domain keyword rule. The cited row and offsets
remain the unmodified source text.

The candidate must be answer-bearing, pass the existing one-way value-shape
veto, and bind the requirement subject in the retrieval-only context. It may
replace Arm 0 only by componentwise structural dominance with at least one
strictly improved structural dimension. A higher reranker score alone never
commits a replacement.

Existing partial/abstain responses are never upgraded. Non-current and account
policy routes keep their dedicated revision resolver and are excluded from this
generic arm.

For prose and list segments, contextual reselection is restricted to the parent
document of the current best structural answer unit. Other parents that happen
to appear among Arm 0's extra cited spans do not authorize a parent jump.
Cross-parent correction belongs to routing or retrieval, not answer-unit
selection. A structurally explicit table row may cross the parent boundary
because its row identity, attribute, and numeric value remain mechanically
auditable.

## Pre-registered gates

Frozen docs 69:

- acceptable-chunk all-groups remains at least 63/69;
- previously passing question regression is zero;
- literal evidence-span regression is zero;
- new false-full is zero;
- exact citation is 100%;
- temporal/revision/preview leakage is zero.

Authored adaptive 24 (diagnostic, not sealed):

- acceptable-chunk all-groups remains at least 20/24;
- literal evidence-span all-covered improves beyond Arm 0's 7/24;
- previously passing question regression is zero;
- new false-full is zero and false-full does not increase above 2/24;
- source coverage is non-decreasing;
- exact citation is 100%;
- temporal leakage is zero.

Passing means only `DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED`. Otherwise the
arm is frozen as `DEVELOPMENT_NO_GO`. The literal evidence-span metric is a
strict mechanical lower bound, not a semantic judge.

## Explicit exclusions

- no new domain/intent keyword rules;
- no candidate pooling across sources;
- no neighboring answer value in retrieval context;
- no LLM, training, reindex, natural-language generation, or blind access;
- no gold input to retrieval, scoring, selection, or commit decisions;
- no question-specific exception.

## Method references

- Anthropic, *Contextual Retrieval* (2024): retrieval text can prepend local
  explanatory context while preserving the underlying chunk.
- Günther et al., *Late Chunking* (2024): chunk representations benefit from
  document context that ordinary isolated chunking discards.
- The existing v3.2 row-atomic sidecar established the same identity-value
  principle for tables; this arm generalizes it to exact prose/list/table
  segments without changing the corpus.
