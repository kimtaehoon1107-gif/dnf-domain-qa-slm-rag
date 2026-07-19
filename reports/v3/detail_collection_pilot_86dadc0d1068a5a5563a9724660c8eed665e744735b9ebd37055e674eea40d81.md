# DNF RAG v3 상세 본문 수집기 파일럿

- 수집 기준 시각: `2026-07-17T21:10:15.3758126+09:00`
- registry SHA-256: `04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a`
- ledger SHA-256: `7af4b91d44a8ad56dc29c766c781e681bf7f36aa27f8c83874d5693daa23dec1`
- preview SHA-256: `a9a5c9cf6abad26bcc0ad305fe3269d7d30f764ad9988981dc53b8ff5c7eed24`
- manifest SHA-256: `38a8d618c4164c9e37c1cfcd8cd13e560644505370ea74529b39b51a21b0bbdd`

## 전체 결과

| selected | success | failed | blocked | parser failed | success rate |
|---:|---:|---:|---:|---:|---:|
| 64 | 63 | 1 | 0 | 0 | 0.984375 |

## 출처별 결과

| source | selected | success | failed | blocked | parser failed | status distribution |
|---|---:|---:|---:|---:|---:|---|
| `dnf_account_policy` | 5 | 5 | 0 | 0 | 0 | current:1, superseded:4 |
| `dnf_event` | 6 | 6 | 0 | 0 | 0 | current:3, expired:3 |
| `dnf_faq` | 16 | 16 | 0 | 0 | 0 | current:14, unknown:2 |
| `dnf_game_guide` | 6 | 6 | 0 | 0 | 0 | current:6 |
| `dnf_monthly_item` | 5 | 4 | 1 | 0 | 0 | current:1, expired:4 |
| `dnf_notice` | 12 | 12 | 0 | 0 | 0 | current:12 |
| `dnf_seria_shop` | 8 | 8 | 0 | 0 | 0 | current:4, expired:4 |
| `dnf_update` | 6 | 6 | 0 | 0 | 0 | current:4, unknown:2 |

## 추출 상태

- heading 포함 row: 47
- table 포함 row / 전체 table: 29 / 142
- image 포함 row / 전체 image: 41 / 657
- date metadata / date signal row: 39 / 44
- price signal row: 24
- guide refresh 비교 / exact match: 6 / 0

## 게이트

- missing_source_success: `[]`
- success_title_empty: `0`
- success_text_empty: `0`
- faq_resolution_errors: `0`
- policy_revision_errors: `0`
- raw_hash_mismatches: `0`
- default_exposure_violations: `0`
- parser_warnings_and_failures_recorded: `True`

## 경고·실패

- `failed` https://df.nexon.com/community/news/monthlyitem: HTTP 404 or empty response
- `dnf_account_policy` https://df.nexon.com/customer/policy/home?revision=2026-03-15&type=1: registry_title_not_found_in_selected_content, navigation_or_footer_signal
- `dnf_account_policy` https://df.nexon.com/customer/policy/home?revision=2016-09-18&type=1: registry_title_not_found_in_selected_content
- `dnf_account_policy` https://df.nexon.com/customer/policy/home?revision=2021-01-21&type=1: registry_title_not_found_in_selected_content
- `dnf_account_policy` https://df.nexon.com/customer/policy/home?revision=2011-09-17&type=1: registry_title_not_found_in_selected_content
- `dnf_account_policy` https://df.nexon.com/customer/policy/home?revision=2025-11-01&type=1: registry_title_not_found_in_selected_content, navigation_or_footer_signal
- `dnf_event` https://df.nexon.com/pg/2026newchargift: body_fallback_navigation_risk, navigation_or_footer_signal, image_content_not_ocr
- `dnf_event` https://df.nexon.com/pg/summerboostup26: body_fallback_navigation_risk, navigation_or_footer_signal, image_content_not_ocr
- `dnf_event` https://df.nexon.com/pr/newfacewithnxp: body_fallback_navigation_risk, image_content_not_ocr
- `dnf_event` https://df.nexon.com/df/pg/realize: registry_title_not_found_in_selected_content, body_fallback_navigation_risk, image_content_not_ocr
- `dnf_event` https://df.nexon.com/pg/arcana: registry_title_not_found_in_selected_content, body_fallback_navigation_risk, image_content_not_ocr
- `dnf_event` https://df.nexon.com/pg/crystalball: registry_title_not_found_in_selected_content, body_fallback_navigation_risk, image_content_not_ocr
- `dnf_faq` https://df.nexon.com/customer/faq?faq_no=4847: image_content_not_ocr
- `dnf_faq` https://df.nexon.com/customer/faq?faq_no=4810: image_content_not_ocr
- `dnf_faq` https://df.nexon.com/customer/faq?faq_no=4987: image_content_not_ocr
- `dnf_faq` https://df.nexon.com/customer/faq?faq_no=5967: short_extracted_text
- `dnf_game_guide` https://df.nexon.com/guide?no=1206: image_content_not_ocr
- `dnf_game_guide` https://df.nexon.com/guide?no=1494: registry_title_not_found_in_selected_content, image_content_not_ocr
- `dnf_game_guide` https://df.nexon.com/guide?no=1269: image_content_not_ocr
- `dnf_game_guide` https://df.nexon.com/guide?no=1391: image_content_not_ocr
- `dnf_game_guide` https://df.nexon.com/guide?no=1512: image_content_not_ocr
- `dnf_monthly_item` https://df.nexon.com/community/news/monthlyitem: fetch_failed
- `dnf_monthly_item` https://df.nexon.com/community/news/seriashop/337: registry_title_not_found_in_selected_content, image_content_not_ocr
- `dnf_monthly_item` https://df.nexon.com/community/news/seriashop/425: registry_title_not_found_in_selected_content, image_content_not_ocr
- `dnf_monthly_item` https://df.nexon.com/community/news/seriashop/593: registry_title_not_found_in_selected_content, image_content_not_ocr
- `dnf_monthly_item` https://df.nexon.com/community/news/seriashop/619: registry_title_not_found_in_selected_content, image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2923190: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2923322: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2926636: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2927550: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2923515: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2927232: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2922724: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2925343: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2922984: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2927771: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2922896: image_content_not_ocr
- `dnf_notice` https://df.nexon.com/community/news/notice/2924930: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/597: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/629: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/423: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/640: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/550: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/552: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/566: image_content_not_ocr
- `dnf_seria_shop` https://df.nexon.com/community/news/seriashop/600: image_content_not_ocr
- `dnf_update` https://df.nexon.com/community/news/update/2927810: image_content_not_ocr
- `dnf_update` https://df.nexon.com/community/news/update/2927233: image_content_not_ocr
- `dnf_update` https://df.nexon.com/community/news/update/2927399: image_content_not_ocr

## 승격 판정

**전체 eligible 상세 수집: GO**

모든 출처의 실제 성공 표본과 95% 이상 fetch success, 특수 locator·raw hash·노출 정책 게이트를 충족했다.

이 파일럿은 선택 표본만 수집했다. DocumentV3, ChunkV3, BM25, Router, 학습은 실행하지 않았다.
