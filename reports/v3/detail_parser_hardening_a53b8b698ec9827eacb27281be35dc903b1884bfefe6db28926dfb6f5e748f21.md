# DNF RAG v3 상세 parser 품질 보강

- parser version: `dnf_detail_parser_hardened_v3.0`
- parsed_at: `2026-07-17T22:29:29.7534422+09:00`
- preview SHA-256: `bf85a72cc4ebd6ffb640a182834c478fbc7fbe88e3c1db42a2ef35f78eda6391`
- manifest SHA-256: `2d0c7b6859512058e21f02e5431b90b55cc0bf2f30b65f3cc2ae8b82fd605cf2`

## 결과

| total | parsed | unavailable redirect | parser failed | normalization candidates |
|---:|---:|---:|---:|---:|
| 982 | 979 | 3 | 0 | 956 |

## 출처별 상태

| source | total | content status | image risk | candidates |
|---|---:|---|---|---:|
| `dnf_account_policy` | 51 | parsed:51 | none:51 | 51 |
| `dnf_event` | 27 | parsed:24, unavailable_redirect:3 | high:5, low:3, medium:16, unknown:3 | 19 |
| `dnf_faq` | 279 | parsed:279 | high:12, low:86, none:181 | 267 |
| `dnf_game_guide` | 125 | parsed:125 | high:1, low:123, none:1 | 124 |
| `dnf_monthly_item` | 14 | parsed:14 | low:14 | 14 |
| `dnf_notice` | 396 | parsed:396 | high:2, low:394 | 394 |
| `dnf_seria_shop` | 72 | parsed:72 | high:3, low:69 | 69 |
| `dnf_update` | 18 | parsed:18 | low:10, none:8 | 18 |

## 품질 게이트

- total: `982`
- parsed: `979`
- unavailable_redirect: `3`
- parser_failed: `0`
- normalization_candidates: `956`
- body_fallback: `0`
- navigation_or_footer_residue: `17`
- unresolved_title_mismatch: `0`
- empty_parsed_title_or_text: `0`
- faq_resolution_errors: `0`
- policy_revision_errors: `0`
- unresolved_guide_changes: `0`
- default_exposed_unavailable: `1`
- default_exposed_high_image_risk: `22`

## 판정

- parser hardening: **NO-GO**
- DocumentV3 promotion: **NO-GO**

이 사이클은 frozen raw를 재추출했으며 네트워크 수집, DocumentV3 재빌드, ChunkV3, 검색, 학습은 실행하지 않았다.
