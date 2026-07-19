# DNF RAG v3 ChunkV3 corpus-wide audit

- chunker: `dnf_offset_chunk_v3.1`
- built_at: `2026-07-18T01:10:47+09:00`
- indexing decision: **GO**

## 요약

| documents | DOM chunks | visual OCR chunks | total chunks | default exposure chunks |
|---:|---:|---:|---:|---:|
| 980 | 3577 | 22 | 3599 | 2527 |

## 출처별

| source | documents | DOM chunks | visual OCR | char p50 | char p95 | char max |
|---|---:|---:|---:|---:|---:|---:|
| `dnf_account_policy` | 51 | 607 | 0 | 1759 | 1797 | 1800 |
| `dnf_event` | 24 | 150 | 8 | 339 | 1387 | 1400 |
| `dnf_faq` | 279 | 282 | 13 | 254 | 785 | 1197 |
| `dnf_game_guide` | 126 | 974 | 1 | 274 | 1348 | 1400 |
| `dnf_monthly_item` | 14 | 49 | 0 | 536 | 1282 | 1400 |
| `dnf_notice` | 396 | 786 | 0 | 353 | 1186 | 1200 |
| `dnf_seria_shop` | 72 | 476 | 0 | 564 | 1396 | 1400 |
| `dnf_update` | 18 | 253 | 0 | 303 | 1360 | 1400 |

## 게이트

- document_count_matches_expected: `True`
- all_expected_sources_represented: `True`
- duplicate_document_ids: `0`
- duplicate_content_ids: `0`
- document_content_id_set_mismatch: `0`
- duplicate_chunk_ids: `0`
- chunk_id_mismatches: `0`
- chunk_index_sequence_mismatches: `0`
- chunker_version_mismatches: `0`
- default_exposure_policy_violations: `0`
- document_without_dom_chunk: `0`
- empty_display_or_retrieval_text: `0`
- evidence_policy_mismatches: `0`
- invalid_offset_source: `0`
- invalid_offsets: `0`
- non_whitespace_coverage_gaps: `0`
- normalized_text_hash_mismatches: `0`
- offset_mismatches: `0`
- orphan_multi_document_chunks: `0`
- oversized_chunks: `0`
- parent_content_hash_mismatches: `0`
- parent_default_exposure_mismatches: `0`
- parent_metadata_mismatches: `0`
- retrieval_text_mismatches: `0`
- schema_missing_required_fields: `0`
- schema_version_mismatches: `0`
- source_config_mismatches: `0`
- token_count_method_mismatches: `0`
- token_count_mismatches: `0`
- unexpected_visual_chunk_parent: `0`
- unknown_parent_document: `0`
- visual_document_without_visual_chunk: `0`

visual OCR chunk는 review_required이며 default exposure=false다.
BM25, dense index, Router, 생성, 평가, 학습은 실행하지 않았다.
