# DNF RAG v3 상세 parser 품질 보강

- parser version: `dnf_detail_parser_hardened_v3.2`
- parsed_at: `2026-07-17T22:29:29.7534422+09:00`
- preview SHA-256: `ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8`
- manifest SHA-256: `ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29`

## 결과

| total | parsed | unavailable redirect | parser failed | normalization candidates |
|---:|---:|---:|---:|---:|
| 982 | 979 | 3 | 0 | 961 |

## 출처별 상태

| source | total | content status | image risk | candidates |
|---|---:|---|---|---:|
| `dnf_account_policy` | 51 | parsed:51 | none:51 | 51 |
| `dnf_event` | 27 | parsed:24, unavailable_redirect:3 | high:5, low:3, medium:16, unknown:3 | 19 |
| `dnf_faq` | 279 | parsed:279 | high:12, low:86, none:181 | 267 |
| `dnf_game_guide` | 125 | parsed:125 | high:1, low:123, none:1 | 124 |
| `dnf_monthly_item` | 14 | parsed:14 | low:14 | 14 |
| `dnf_notice` | 396 | parsed:396 | low:394, medium:2 | 396 |
| `dnf_seria_shop` | 72 | parsed:72 | low:71, medium:1 | 72 |
| `dnf_update` | 18 | parsed:18 | low:10, none:8 | 18 |

## 품질 게이트

- total: `982`
- parsed: `979`
- unavailable_redirect: `3`
- parser_failed: `0`
- normalization_candidates: `961`
- body_fallback: `0`
- navigation_or_footer_residue: `0`
- unresolved_title_mismatch: `0`
- empty_parsed_title_or_text: `0`
- faq_resolution_errors: `0`
- policy_revision_errors: `0`
- raw_hash_mismatches: `0`
- unresolved_guide_changes: `0`
- default_exposed_unavailable: `1`
- default_exposed_high_image_risk: `18`

## 판정

- parser hardening: **GO**
- DocumentV3 promotion: **NO-GO**

이 사이클은 frozen raw를 재추출했으며 네트워크 수집, DocumentV3 재빌드, ChunkV3, 검색, 학습은 실행하지 않았다.
