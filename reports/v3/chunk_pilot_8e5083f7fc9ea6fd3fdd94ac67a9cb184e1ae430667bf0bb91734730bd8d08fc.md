# DNF RAG v3 ChunkV3 파일럿 보고서

- chunker: `dnf_offset_chunk_pilot_v3.1`
- built_at: `2026-07-18T00:30:00+09:00`
- manifest SHA-256: `e176dbccb42a0be6fa9b3aadebff9e55ee00be1e5dacdee3967c6e35bfdd2079`

## 결과

| documents | DOM chunks | visual OCR chunks | table/mixed | default exposure chunks |
|---:|---:|---:|---:|---:|
| 63 | 561 | 22 | 183 | 348 |

## 출처별

| source | documents | DOM chunks | visual chunks |
|---|---:|---:|---:|
| `dnf_account_policy` | 5 | 60 | 0 |
| `dnf_event` | 6 | 50 | 8 |
| `dnf_faq` | 16 | 16 | 13 |
| `dnf_game_guide` | 8 | 165 | 1 |
| `dnf_monthly_item` | 4 | 14 | 0 |
| `dnf_notice` | 12 | 29 | 0 |
| `dnf_seria_shop` | 6 | 22 | 0 |
| `dnf_update` | 6 | 205 | 0 |

## 게이트

- selection_count_is_63: `True`
- all_eight_sources_represented: `True`
- all_four_statuses_represented: `True`
- all_18_visual_documents_represented: `True`
- selected_document_without_dom_chunk: `0`
- offset_mismatches: `0`
- duplicate_chunk_ids: `0`
- empty_display_or_retrieval_text: `0`
- oversized_atomic_chunks: `0`
- orphan_multi_document_chunks: `153`
- default_exposure_policy_violations: `0`
- visual_ocr_default_exposure_violations: `0`

전체 ChunkV3 진입: **NO-GO**

visual OCR chunk는 review_required이며 default exposure=false다. BM25, dense index, Router, 학습은 실행하지 않았다.
