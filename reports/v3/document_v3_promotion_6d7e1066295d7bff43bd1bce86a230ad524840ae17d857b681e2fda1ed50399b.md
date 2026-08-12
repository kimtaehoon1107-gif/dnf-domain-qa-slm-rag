# DNF RAG v3 revision-aware DocumentV3 승격 보고서

- builder: `dnf_normalized_corpus_builder_v3.2`
- built_at: `2026-08-07T19:12:13+09:00`
- manifest SHA-256: `ebf0a8514591e88def4157aa2b97b9d3e67a53b60586a6693b54ec13c52d1003`

## 결과

| candidates | preserved revisions | documents | contents | excluded | default exposure |
|---:|---:|---:|---:|---:|---:|
| 995 | 1 | 996 | 996 | 3 | 888 |

## 출처별 문서

| source | rows | default exposure |
|---|---:|---:|
| `dnf_account_policy` | 52 | 1 |
| `dnf_event` | 28 | 28 |
| `dnf_faq` | 281 | 281 |
| `dnf_game_guide` | 127 | 126 |
| `dnf_monthly_item` | 14 | 1 |
| `dnf_notice` | 402 | 402 |
| `dnf_seria_shop` | 70 | 31 |
| `dnf_update` | 22 | 18 |

## 게이트

- all_eligible_urls_accounted_for: `True`
- excluded_documents_are_overlay_backed: `True`
- all_material_revisions_preserved: `True`
- document_content_id_sets_match: `True`
- empty_title_or_text: `0`
- invalid_status: `0`
- default_exposure_policy_violations: `0`
- visual_ocr_has_separate_unverified_provenance: `True`
- raw_hash_mismatches: `0`

DocumentV3 promotion: **GO**

OCR text는 DOM text와 분리된 비검수 보조 evidence로 보존했다. ChunkV3, 검색, 구조화 store, 학습은 실행하지 않았다.
