# v3.2 Arm 2 — Offset-preserving evidence eligibility mask

Status: development-only A/B, not canonical, not runtime-promoted.

## Suitability decision

Replacing the global retrieval text is not repeated in this Arm. The prior P2 hygiene experiment changed the score distribution and regressed grounded answers from 73/82 to 72/82 while increasing false-full from 9/82 to 10/82. That approach is unsuitable as a promotion candidate.

Arm 2 tests the narrower measured boundary: retrieval remains frozen, while spans inside known navigation/footer and account-policy revision-selector ranges are ineligible for evidence selection. This can remove citation contamination without changing candidate ranks.

## Contract

- Dirty canonical `display_text`, chunk IDs, parent IDs, and offsets remain immutable.
- `evidence_text_clean` is a concatenation of allowed exact substrings of the original display text.
- `evidence_to_original_offset_map` maps every clean range back to its original offsets.
- `excluded_ranges` may contain only the measured navigation/footer/listing tail or policy revision-selector/table-of-contents ranges.
- A cited span is allowed only when it is fully contained in one mapped original range.
- A chunk containing only a measured excluded range remains in the immutable corpus but has no evidence-eligible range; this is not deletion.
- Citation text is always sliced from the original dirty canonical text; no paraphrase or synthetic offset is permitted.
- Retrieval, planner, reranker, table Arm 1, gold, and questions are unchanged.

## A/B gate

The evidence mask is retained only if it blocks measured contaminated citations while preserving grounded 73/82, creating no new false-full, preserving exact citation validity at 100%, and leaving reject 11/11, realtime safe-abstain 2/2, and temporal exposure unchanged. Failure is frozen as development-only NO-GO and the dirty canonical behavior remains authoritative.
