# DNF RAG v3 상세 parser 품질 보강

## 범위

이 사이클은 전체 상세 수집에서 freeze한 raw snapshot 719개를 다시 읽어 982개 registry row를 source-aware parser로 재추출했다. 네트워크 요청, raw 수정, DocumentV3 재빌드, ChunkV3, 구조화 store, 검색, 학습은 실행하지 않았다.

- parser version: `dnf_detail_parser_hardened_v3.2`
- fixed `parsed_at`: `2026-07-17T22:29:29.7534422+09:00`
- 입력 ledger SHA-256: `0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b`
- 입력 preview SHA-256: `e48f58e205a7001e23e3286cc7df2d467bf8b549f9ce449b82a46a6accf8e1dd`
- 입력 collection manifest SHA-256: `f3003742b55a515e51c2abaee5a993cea9b1f108297f59c74a9aeaa201f87e97`
- registry SHA-256: `04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a`

## 보강 규칙

1. 표준 상세 페이지는 출처별 article/section selector만 허용하고 `body` 또는 document fallback을 실패로 처리한다.
2. 유효한 custom event page는 `#wrap`을 선택한 뒤 진행 이벤트 바, 로그인 바, 공용 footer, 보안 layer, script/style을 구조적으로 제거한다. 이벤트별 유의사항과 popup item 정보는 보존한다.
3. canonical path가 다른 경로로 redirect되면 HTTP 200이어도 성공 본문으로 만들지 않고 `unavailable_redirect`로 기록한다.
4. FAQ는 listing snapshot의 정확한 `data-no`, 운영정책은 선택된 revision option을 다시 검증한다.
5. 제목은 본문 일치 외에도 공식 guide registry, 공식 listing, 검증된 policy revision이라는 provenance 상태로 구분한다. 설명되지 않은 mismatch만 blocker다.
6. 이미지 alt는 `[IMAGE_ALT]`로 보존하지만 OCR 결과로 간주하지 않는다. DOM text 길이, image 수, table, 출처 특성으로 `none/low/medium/high/unknown` 위험을 분류한다.
7. 정책 본문에서 이용약관·개인정보처리방침·고객센터를 함께 언급하는 것은 navigation residue가 아니다. 정확한 policy revision node가 검증된 경우 정상 본문으로 처리한다.

## 결과

| source | total | parsed | unavailable | normalization candidates |
|---|---:|---:|---:|---:|
| `dnf_account_policy` | 51 | 51 | 0 | 51 |
| `dnf_event` | 27 | 24 | 3 | 19 |
| `dnf_faq` | 279 | 279 | 0 | 267 |
| `dnf_game_guide` | 125 | 125 | 0 | 124 |
| `dnf_monthly_item` | 14 | 14 | 0 | 14 |
| `dnf_notice` | 396 | 396 | 0 | 396 |
| `dnf_seria_shop` | 72 | 72 | 0 | 72 |
| `dnf_update` | 18 | 18 | 0 | 18 |
| **합계** | **982** | **979** | **3** | **961** |

품질 게이트는 다음과 같다.

- parser failed: 0
- body/document fallback: 0
- navigation/footer residue: 0
- 설명되지 않은 title mismatch: 0
- parsed row의 빈 title/text: 0
- FAQ locator 오해결: 0/279
- policy revision 오해결: 0/51
- raw hash 불일치: 0
- 미해결 guide material change: 0

title provenance는 본문 직접 일치 888, policy revision 검증 51, guide registry 36, official listing 4, 원문 부재 URL의 official listing 3이다.

## 원문 부재 redirect

다음 3개 URL은 수집 당시 상세 원문 대신 던파 메인으로 redirect됐다. raw에서 본문을 복구하거나 생성하지 않았다.

- `https://df.nexon.com/df/pg/13th` — current/default exposure이므로 DocumentV3 blocker
- `https://df.nexon.com/pg/arcana` — expired/non-default
- `https://df.nexon.com/pg/crystalball` — expired/non-default

## 이미지 의존 위험

전체 분포는 `none 241 / low 701 / medium 19 / high 18 / unknown 3`이다. high 18개는 모두 default exposure이며 normalization candidate에서 제외했다.

- custom event 5개: CSS 배경 또는 이미지 대비 DOM text 부족
- FAQ 12개: 단계 안내나 수치 설명이 screenshot에 의존
- game guide 1개: `guide?no=1284` 개인상점, 이미지 7개 대비 DOM text 505자

공지의 다수 이모티콘 이미지 2건은 공식 텍스트가 충분해 medium, 세리아 상점 정보성 문서는 수천 자와 표가 있어 low/medium으로 판정했다. high URL 전체는 canonical report의 `default_exposed_high_image_risk_urls`에 기록했다.

## Guide revision 판정

`guide?no=1535`의 길이 변화는 truncation이 아니라 공식 갱신이다. baseline은 2026-07-05 수집본이고 새 raw에는 `2026-07-16에 업데이트` 문구와 서약 포인트 관련 신규 내용이 있다. `official_revision_after_baseline`으로 기록했으며 revision-aware DocumentV3에서 새 revision으로 보존해야 한다.

## Canonical artifacts

- hardened preview: `data/v3/collections/detail_hardened_extraction_preview_ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8.jsonl`
- preview SHA-256: `ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8`
- parser manifest: `data/v3/collections/detail_parser_hardening_manifest_ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29.json`
- manifest SHA-256: `ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29`
- report: `reports/v3/detail_parser_hardening_cd65971ef73d7adbd3221a9dafcac483db3cfd2e845523f8274888a3cce25e1a.json` 및 `.md`
- report JSON SHA-256: `cd65971ef73d7adbd3221a9dafcac483db3cfd2e845523f8274888a3cce25e1a`

동일 preview를 재freeze했을 때 preview, manifest, report hash가 재현됐다. 실험 중 생성된 v3.0/v3.1 artifact는 content-addressed 이력이고 위 v3.2 artifact만 canonical이다.

## 판정과 다음 단계

- parser hardening: **GO**
- 현재 DocumentV3 전체 자동 승격: **NO-GO**

다음 선행 작업은 default-exposed high-image 18건의 visual evidence/OCR 파일럿과 `df/pg/13th`의 discovery 상태 교정이다. 이 두 항목을 해결하거나 명시적으로 normalization에서 제외하는 계약을 승인한 뒤 revision-aware DocumentV3를 재빌드한다.
