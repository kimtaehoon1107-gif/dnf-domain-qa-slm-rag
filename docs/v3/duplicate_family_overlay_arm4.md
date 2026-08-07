# v3.2 Arm 4 — duplicate-family overlay contract

## Purpose

Cross-source pages can describe the same official product or campaign while carrying
different facts. Event pages are authoritative for participation, rewards, and claim
methods; shop and monthly-item pages are authoritative for price, sale state,
components, trade type, and deletion date. Therefore title-equal documents must not
be collapsed into one document.

## Contract

- The overlay is additive. Normalized documents, chunks, offsets, and gold IDs remain unchanged.
- A family starts only from the frozen cross-source normalized-title candidates.
- `duplicate_family_id` is a deterministic hash of the normalized title and sorted member document IDs.
- Every member keeps its original document ID, content hash, URL, source, and title.
- `source_role` records why a member remains independently useful.
- `preferred_source_by_attribute` is metadata for a future selector; this arm does not change retrieval or ranking.
- Exact normalized-title equality is only a candidate relation, not proof of semantic identity. Each family remains `requires_semantic_confirmation`.
- No member is deleted, merged, hidden, or used for runtime deduplication in this arm.

## A/B gate

Arm 4 is an additive metadata candidate only when all 14 candidate documents receive
a role, all seven candidate groups receive deterministic family IDs and attribute
preferences, no source role is collapsed, and corpus/evaluation IDs remain unchanged.
Runtime candidate diversity is explicitly out of scope until a separate answer-quality
A/B can demonstrate improvement without recall or citation regression.
