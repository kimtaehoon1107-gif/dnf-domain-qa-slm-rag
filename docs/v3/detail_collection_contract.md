# DNF RAG v3 상세 본문 수집기 파일럿 계약

## 범위와 frozen 입력

이 사이클은 전체 eligible 982개를 수집하기 전의 출처별 파일럿이다. 입력은 다음 discovery snapshot으로 고정했다.

- registry SHA-256: `04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a`
- registry manifest SHA-256: `4cbd8c441fd694ec16ad30b6b42c4c6f28326dc9a768d883399419ef87ee9ea2`
- collector version: `dnf_detail_pilot_v3.0`
- 최종 수집 기준 시각: `2026-07-17T21:11:46.2438189+09:00`

상세 본문 raw snapshot과 extraction preview만 생성했다. DocumentV3 재빌드, ChunkV3, 구조화 store 전체 생성, BM25, Router, 학습은 수행하지 않았다.

## 결정론적 표본 선택

URL을 직접 하드코딩하지 않고 frozen registry row를 `source_id`, `source_kind`, `status`, `category`, eligibility로 나눈 뒤 canonical URL SHA-256 순서로 선택한다. registry row 순서를 뒤집어도 같은 64개가 선택되어야 한다.

| source | 표본 | 분포 |
|---|---:|---|
| `dnf_notice` | 12 | 6개 `source_kind` 각 2개 |
| `dnf_update` | 6 | live patch 4, preview control 2 |
| `dnf_event` | 6 | current 3, expired 3 |
| `dnf_game_guide` | 6 | 서로 다른 category 6개 |
| `dnf_faq` | 16 | 8개 상위 bucket 각 2개 |
| `dnf_account_policy` | 5 | current, recent, 중간 2, oldest |
| `dnf_seria_shop` | 8 | active 기간 유/무, expired eligible/control 각 2 |
| `dnf_monthly_item` | 5 | current 1, expired eligible 2, expired control 2 |

frozen registry에 `upcoming` 이벤트가 0개여서 event 표본은 current 3개와 expired 3개로 조정했다. FAQ의 실제 category가 8개 계약 범주보다 세분화돼 있어 제목과 category signal을 사용해 아이디정보/보안, 설치/실행, 게임문의, 복구, 결제, PC방, 이벤트, 던파ON으로 매핑했다. 이벤트 FAQ 2개는 non-eligible·`default_exposure=false` 통제 표본이다.

## raw snapshot과 ledger

- HTTP raw bytes를 SHA-256로 식별해 `data/v3/detail_snapshots/<source_id>/raw_detail_<sha256>.html`에 저장한다.
- 같은 경로에 다른 bytes를 덮어쓰지 않는다.
- FAQ는 synthetic canonical URL을 GET하지 않고 registry의 `listing_url`을 raw로 저장한 뒤 `data-no` 항목을 해결한다. 같은 listing page를 공유하는 FAQ row는 raw snapshot을 공유할 수 있다.
- 운영정책은 registry revision URL을 fetch한 뒤 `#revisionList option[selected]` 값이 요청 revision과 정확히 같은지 검증한다.
- canonical URL 정규화는 현재 이달의 아이템 `/monthlyitem/`의 마지막 slash를 제거하지만, 실제 endpoint는 slash 없이 404를 반환한다. collector는 canonical identity를 바꾸지 않고 fetch URL에만 slash를 복구한다.

최종 ledger는 64 row이고, FAQ listing page 공유를 포함한 고유 raw snapshot은 60개다. `success`, `failed`, `blocked`, `parser_failed`를 구분하며 모든 선택 row가 하나의 outcome을 가져야 한다.

## extraction preview

- 제목, 본문, heading, table, image, 날짜, 유효 기간, 가격 signal을 기록한다.
- HTML table은 `[TABLE]` 블록과 `| cell | cell |` row로 변환해 행·열 관계를 남긴다.
- 이미지가 하나라도 있으면 `image_content_not_ocr`을 남긴다. OCR은 이 사이클 범위 밖이다.
- body fallback, navigation/footer signal, registry title 미발견, 짧은 본문을 warning으로 남긴다.
- 가이드는 기존 `data/raw/guide_docs.jsonl` text와 길이·hash를 비교한다. 6개 모두 비교됐고 실제 길이 비율은 약 1.03~1.13으로, 심각한 절단 signal은 없었다.

## 최종 freeze

- ledger: `data/v3/collections/detail_collection_ledger_6cd39a7473272b78a0581ae739610ce73f8f7a9fa2134d5afaef919dfa18a3b7.jsonl`
- preview: `data/v3/collections/detail_extraction_preview_0a1a450075579dd3569ecde66fc813bf65b7660c5390f68bb995a9fd3839233a.jsonl`
- manifest: `data/v3/collections/detail_collection_manifest_71386a3b3d6bb627422d14eccf4c29e22da5d8e666793c4e428bb93be506a07a.json`
- report: `reports/v3/detail_collection_pilot_b06f5df59bbab93ff9852583195f9037bf93c727d9da1ee2e906c2e7ca3d17b0.json` 및 `.md`

최종 파일럿은 64/64 success, blocked 0, parser failed 0이다. success row의 빈 title/text, FAQ locator 오해결, policy revision 오해결, raw hash 불일치, `default_exposure` 정책 위반은 모두 0이다.

preview는 heading 48 row, table 29 row/142개, image 42 row/658개, date signal 45 row, price signal 25 row를 기록했다. warning은 image OCR 미수행 42, registry title 미발견 13, custom event body fallback 6, navigation/footer signal 4, short text 1건이며 URL별로 report에 남겼다.

## 승격 판정

전체 982개 raw detail 수집은 **GO**다. 이 판정은 raw 수집과 최소 preview parser의 실행 가능성에 대한 것이다. custom event page의 body fallback 정제, registry title alignment, 이미지 핵심 정보 검수는 최종 DocumentV3 승격 전에 별도 quality gate로 유지한다.
