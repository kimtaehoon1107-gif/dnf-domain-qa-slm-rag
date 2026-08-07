# DNF RAG v3 visual evidence/OCR 파일럿

## 범위

상세 parser hardening에서 `default_exposure=true`, `image_dependency_risk=high`로 남은 18개 문서만 대상으로 이미지·페이지 전용 CSS 자산을 수집하고 Windows OCR로 보조 근거를 생성했다. 기존 raw detail snapshot, discovery registry, DocumentV3 artifact는 수정하지 않았다. DocumentV3 재빌드, ChunkV3, 검색, 학습도 실행하지 않았다.

- collector/parser version: `dnf_visual_evidence_pilot_v3.1`
- fixed `fetched_at`: `2026-07-17T23:28:32.5730462+09:00`
- registry SHA-256: `04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a`
- full detail ledger SHA-256: `0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b`
- hardened preview SHA-256: `ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8`
- parser hardening manifest SHA-256: `ae4f5f31d2ed59a30a29124512b5f5c47d1edfa6355833f57c0895e5d1895c29`

## 수집·판정 계약

1. hardened parser가 선택한 본문 node의 `<img>`, inline style 이미지, custom event의 inline CSS와 `bbscdn.df.nexon.com` 페이지 전용 stylesheet만 탐색한다. 공용 navigation/footer 자산은 대상이 아니다.
2. raw asset bytes는 SHA-256 파일명으로 `data/v3/visual_assets/<source_id>/`에 immutable 저장한다. 같은 bytes는 같은 경로를 사용하며 overwrite하지 않는다.
3. OCR은 Windows `Windows.Media.Ocr`의 `ko` recognizer를 사용한다. 첫 image frame을 흰 배경 RGB로 변환하고 최대 변을 2,400px로 제한한다. OCR 실패와 빈 결과를 성공 텍스트로 꾸미지 않는다.
4. 직접 본문 이미지(`content_img`, `content_style_url`)의 fetch 또는 OCR 실패는 항상 blocker다.
5. CSS에서만 발견된 이미지가 HTTP 404이고 다른 성공 이미지의 OCR이 충분한 경우에만 그 자산을 보조·stale CSS 참조로 허용한다. 충분한 OCR은 한글 10자 이상이면서 signal 40자 이상, 또는 signal 30자 이상과 숫자 2자 이상이다. 허용한 URL도 ledger와 report failure row에 그대로 남긴다.
6. redirect로 원문을 잃은 3개 discovery row는 frozen registry를 수정하지 않고 correction overlay에서 `effective_status=unavailable_redirect`, collection/default exposure false로 만든다.
7. 1차 실제 수집 ledger를 판정 규칙 보정 후 재사용할 때는 `--reuse-asset-ledger`로 네트워크와 OCR을 다시 실행하지 않는다. 재사용 ledger의 SHA-256을 최종 manifest에 기록한다.

OCR text는 이미지 의존 문서의 누락 정보를 보완하는 비검수 보조 근거다. 단독으로 authoritative fact로 취급하지 않으며, 다음 DocumentV3 빌드에서도 DOM text와 분리된 provenance 및 extraction warning을 유지해야 한다.

## 실제 결과

| source | 대상 문서 | 해결 | CSS 404 허용 포함 | 이미지 자산 | OCR 문자 |
|---|---:|---:|---:|---:|---:|
| `dnf_event` | 5 | 5 | 2 | 147 | 7,319 |
| `dnf_faq` | 12 | 12 | 0 | 25 | 3,753 |
| `dnf_game_guide` | 1 | 1 | 0 | 7 | 711 |
| **합계** | **18** | **18** | **2** | **179** | **11,902** |

- asset ledger row 180개: image 179, stylesheet 1
- unique immutable snapshot 166개
- fetch success 177, HTTP 404 3, blocked 0
- OCR success 176, OCR engine failure 0, fetch 실패로 미실행 3
- OCR non-empty image 109
- partial/unresolved 문서 0
- raw asset hash mismatch 0
- normalization candidate: 961에서 979로 증가

HTTP 404 3건은 다음과 같다.

- `2026newchargift`: 직후 동일 selector 규칙에서 덮어써지는 공용 확대 아이콘 1개
- `aradfishing`: 성공한 직접 내용 이미지 위에 사용되는 오래된 inline CSS tooltip 배경·label 2개

두 문서 모두 다른 실제 이미지에서 충분한 OCR 근거를 확보했다. 실패 URL은 삭제하거나 성공으로 바꾸지 않았고 `resolved_with_tolerated_css_404`로 구분했다.

redirect correction overlay는 3개 row를 기록했다. 이 중 `df/pg/13th` 한 건이 기존 current/default row이며, overlay 적용 후 default exposure에서 제외된다. `arcana`, `crystalball`은 원래 expired/non-default였다.

## Canonical artifacts

- asset ledger: `data/v3/visual_evidence/visual_asset_ledger_9b871e8ed168bb155c183165713c944afbed09e72b68c8ea4a633541bcc82df8.jsonl`
- document evidence: `data/v3/visual_evidence/visual_document_evidence_c7362de31d59ee1f0877477caa8c5d4848fdbdf40719b5c64cdb861c29469d38.jsonl`
- correction overlay: `data/v3/visual_evidence/discovery_correction_overlay_0841fdad1f8c80dcda51036162b524ed4c7cf3cd31fb2bdb26a915cf77ddf61b.jsonl`
- manifest: `data/v3/visual_evidence/visual_evidence_manifest_ff585eb897627edd9bceae3f643fe5ac23904a07fcbed7b5fbe51cb59e64050b.json`
- report: `reports/v3/visual_evidence_pilot_e40f7acd38a3848e6da2c0637f6ebe4ee76dff553ab2ef8f73b5c97e3c209873.json` 및 `.md`

1차 v3.0 artifact는 immutable 실행 이력이며 canonical 판정은 위 v3.1 artifact만 사용한다.

## 판정과 다음 단계

- targeted visual evidence/OCR: **GO**
- revision-aware DocumentV3 재빌드 진입: **GO**

GO는 DocumentV3가 이미 재빌드됐다는 뜻이 아니다. 다음 사이클에서 frozen registry, hardened preview, visual document evidence, correction overlay를 함께 입력으로 사용해 revision-aware DocumentV3를 새 content-addressed artifact로 빌드해야 한다. 이때 기존 188개 baseline을 덮어쓰지 않고, 979개 candidate와 3개 unavailable exclusion 관계를 검증한다.
