# Q4 docs-only false-full audit contract

## Purpose

This development-only audit freezes the six docs-only false-full cases that
remain after the bounded candidate-source fallback A/B. It changes no question,
gold, corpus, route, retrieval, selector, or assembler output.

Each case receives exactly one earliest-failure stage:

- `ROUTING_SOURCE_SCOPE`: the hard route searched the wrong primary source;
- `RETRIEVAL`: the correct source was in scope but acceptable evidence never
  reached the frozen candidate pool;
- `SELECTION_SUPPORT`: acceptable evidence was available, but the selector
  chose a heading, adjacent attribute, or otherwise non-answering span;
- `MEASUREMENT`: the cited official evidence is actually acceptable and the
  strict gold is incomplete.

The stage order is `ROUTING_SOURCE_SCOPE -> RETRIEVAL -> SELECTION_SUPPORT ->
MEASUREMENT`. Only the first broken stage is counted. Secondary symptoms remain
in the case rationale.

The earlier semantic A/B/C/D label is also preserved for continuity. Gold IDs
are used only for this diagnostic. No case-specific runtime rule is created.

