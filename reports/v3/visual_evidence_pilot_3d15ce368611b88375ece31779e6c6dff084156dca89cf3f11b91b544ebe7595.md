# DNF RAG v3 visual evidence/OCR 파일럿

- visual version: `dnf_visual_evidence_pilot_v3.1`
- fetched_at: `2026-07-17T23:28:32.5730462+09:00`
- manifest SHA-256: `ff585eb897627edd9bceae3f643fe5ac23904a07fcbed7b5fbe51cb59e64050b`

## 결과

| targets | resolved | partial | unresolved | image assets | OCR chars |
|---:|---:|---:|---:|---:|---:|
| 18 | 18 | 0 | 0 | 179 | 11902 |

## 출처별 결과

| source | documents | status | assets | OCR chars |
|---|---:|---|---:|---:|
| `dnf_event` | 5 | resolved:3, resolved_with_tolerated_css_404:2 | 147 | 7319 |
| `dnf_faq` | 12 | resolved:12 | 25 | 3753 |
| `dnf_game_guide` | 1 | resolved:1 | 7 | 711 |

## 게이트

- target_documents: `18`
- resolved_documents: `18`
- resolved_with_tolerated_css_404: `2`
- partial_documents: `0`
- unresolved_documents: `0`
- normalization_candidates_after_visual: `979`
- asset_rows: `180`
- image_asset_rows: `179`
- stylesheet_rows: `1`
- asset_fetch_success: `177`
- asset_fetch_failed: `3`
- asset_fetch_blocked: `0`
- tolerated_css_404_assets: `3`
- ocr_success: `176`
- ocr_failed: `3`
- ocr_nonempty_assets: `109`
- ocr_total_chars: `11902`
- correction_overlay_rows: `3`
- default_exposure_corrections: `1`
- unresolved_default_documents: `0`
- asset_hash_mismatches: `0`

## 판정

- visual evidence: **GO**
- DocumentV3 promotion: **GO**

이 파일럿은 targeted image/CSS asset과 OCR evidence만 생성했다. DocumentV3, ChunkV3, 검색, 학습은 실행하지 않았다.
