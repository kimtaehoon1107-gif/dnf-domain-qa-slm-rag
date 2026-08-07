# Submission Roadmap T5 실행 결과 — 2026-08-07

## 결론

T5 코퍼스 갱신은 **K2 진입 전 롤백 판정**이다.

신규 문서 발견과 원문 수집은 성공했지만, 새 현재 이벤트 페이지 1건을 기존 hardened parser가 처리하지 못했다. 지시서의 “게이트 실패 후 고쳐서 계속하지 말 것”에 따라 parser를 수정하거나 문서를 임의 제외하지 않았고, 정규화·청킹·인덱스·런타임 전환·Qwen 비교를 실행하지 않았다.

기존 2026-07-17 런타임 상수 4개와 기존 artifact는 그대로다.

## K0 기준선 — PASS

- 고정 시각: `2026-08-07T19:12:13+09:00`
- 문서: 980
- 청크: 3,599
- 봉인 A6 문항: 32
- 봉인 참조 evidence unit: 62
- 고유 `chunk_id`: 33
- 고유 `document_id`: 28
- 기존 코퍼스 현존: 33/33
- 기준선 JSON: `reports/v3/corpus_refresh_baseline_20260807.json`

런타임 입력은 다음 네 경로로 고정돼 있었고, 기준선 JSON에 경로·SHA-256·크기를 기록했다.

1. BM25 manifest
2. dense manifest
3. chunk JSONL
4. normalized document JSONL

GPU 사전 점검은 통과했다. RTX 5070 Laptop GPU 사용률은 0%였고 Python·Ollama 연산 프로세스가 없었다. `nvidia-smi`의 권한 미확인 PID 2528은 Windows `dwm`으로 확인했다.

## K1 발견·수집 — PASS

### URL 발견

- 실행 시간: 220.4초
- 발견 전체: 13,264
- 현재 정책상 적격 URL: 998
- 기존 코퍼스에 이미 포함: 952
- 신규 또는 미수집: 46
- blocked source: 0
- partial source: 0
- detail collection decision: GO

| source | 적격 | 기존 포함 | 신규·미수집 |
|---|---:|---:|---:|
| `dnf_account_policy` | 52 | 51 | 1 |
| `dnf_event` | 31 | 16 | 15 |
| `dnf_faq` | 281 | 279 | 2 |
| `dnf_game_guide` | 126 | 125 | 1 |
| `dnf_monthly_item` | 14 | 14 | 0 |
| `dnf_notice` | 402 | 381 | 21 |
| `dnf_seria_shop` | 70 | 68 | 2 |
| `dnf_update` | 22 | 18 | 4 |

주요 artifact:

- registry: `data/v3/discovery/source_registry_4c5ff1fb05f9d2eb9962caa03f87a09190950291d1338eeae579c2ae0f292ff1.jsonl`
- registry manifest: `data/v3/discovery/source_registry_manifest_15938776b1e975272aa78c1c41503be9ffb45d32ce2eacc9a3726f012ca7cd01.json`
- discovery report: `reports/v3/source_discovery_coverage_0545b7de6407ca17b65e544c932d8feb24ffd8f057e78b902cddb6bebc9284c3.json`

### 상세 수집

- 실행 시간: 341.3초
- 선택: 998
- 성공: 998
- 실패·차단·parser failed: 0
- 재시도: 998건 모두 0회
- 고유 raw snapshot: 733
- full collection decision: GO

주요 artifact:

- ledger: `data/v3/collections/detail_full_collection_ledger_a9230fa5c2a8f70df77749db7bf37a0a307506d27fa25d588c9310accacc1a6f.jsonl`
- preview: `data/v3/collections/detail_full_extraction_preview_310ac06f797f216bdf096322bac31954b755256cef822584325b1089ef06fb82.jsonl`
- manifest: `data/v3/collections/detail_full_collection_manifest_e881ecf5c0aa5f525a72613f2fb3f4d7b61635f7bd1940bfacb520b6a53ed74d.json`
- report: `reports/v3/detail_full_collection_3041e81cc83d3d19c821f2e48d9837e3cad9d109dfb4d6723a305d309aa69f18.json`

기존 artifact를 삭제하거나 덮어쓰지 않았다.

## K2 선행 parser hardening — FAIL, 즉시 중단

정규화기는 hardened preview를 필수 입력으로 요구한다. 따라서 기존 `dnf_detail_parser_hardened_v3.2`를 같은 고정 시각로 실행했다.

- 실행 시간: 58.2초
- 전체: 998
- parsed: 994
- unavailable redirect: 3
- parser failed: 1
- normalization candidate: 977
- parser hardening decision: **NO-GO**
- DocumentV3 promotion decision: **NO-GO**

실패 문서:

| 항목 | 값 |
|---|---|
| URL | `https://df.nexon.com/pg/21stpcb` |
| 제목 | 시원한 물살 가르는 21주년 Special PC방 |
| 상태 | current · default exposure |
| HTTP 수집 | 200 · 성공 · 재시도 0 |
| raw SHA-256 | `b9a61c93dedf382657bfb57d8afe336d42f90266145ef2882993bab767f9090b` |
| 직접 재현 오류 | `AttributeError: 'NoneType' object has no attribute 'get'` |
| 최초 실패 위치 | `src/v3/harden_detail_parsers.py:133` |

직접 재현한 호출 스택에서 `structured_text_hardened()`가 BeautifulSoup image 노드의 `attrs=None` 상태를 고려하지 않고 `image.get("alt")`를 호출했다. 이것은 네트워크 수집 실패가 아니라 **새 페이지의 HTML 구조가 기존 parser 가정을 깨뜨린 사건**이다.

그 밖에 기존과 같은 원문 부재 redirect 3건과 default-exposed high-image-risk 17건도 남아 있다. 이들을 임의 제외하거나 parser/overlay를 수정하면 사전 등록된 라운드와 원인 분리가 깨지므로 적용하지 않았다.

parser artifact:

- hardened preview: `data/v3/collections/detail_hardened_extraction_preview_092ad26dec954f45a252fbc41f5cf4b79ed444232bcbf8dd82b10ecd7e3e3947.jsonl`
- manifest: `data/v3/collections/detail_parser_hardening_manifest_2da56339b15517463db6d62e647cb688f443bde47e766ae251144567f53eb7d6.json`
- report: `reports/v3/detail_parser_hardening_efd9622f0c11e98ea55bbe31a4757f6270c8fc66206a934839a560a43671d831.json`

## K2~K5

| 단계 | 결과 | 이유 |
|---|---|---|
| K2 정규화·청킹 | 미실행 | hardened parser NO-GO |
| K2 신규 코퍼스 33/33 | 측정 불가 | 새 chunk artifact를 만들지 않음 |
| K3 BM25·dense 재빌드 | 미실행 | K2 미통과 |
| K4 런타임 전환·pytest | 미실행 | 새 인덱스·코퍼스 없음 |
| K5 adaptive 32 | 미실행 · Qwen 0회 | 런타임 전환 없음 |

## K6 판정 — ROLLBACK

실제 런타임 전환 전 중단했으므로 되돌릴 상수 변경은 없다. 여기서의 rollback은 **새 수집물을 런타임에 채택하지 않고 기존 2026-07-17 snapshot을 유지한다**는 뜻이다.

- `src/v3/retrieve_v3.py` 상수 변경: 0줄
- 기존 코퍼스·인덱스 삭제/덮어쓰기: 0건
- 봉인 artifact 수정·재실행: 0건
- Qwen 호출: 0회
- `PORTFOLIO.md`·`README.md` snapshot 숫자 변경: 없음

## 다음 라운드의 정확한 시작점

새 별도 라운드에서 `BeautifulSoup`의 속성 없는 image 노드를 처리하는 최소 parser 수정과 해당 HTML 회귀 테스트를 먼저 작성한다. 그 수정이 기존 998건 hardening gate를 통과한 뒤에만 이 코퍼스 갱신의 K2부터 다시 시작한다.

이번 결과는 “3주간 신규 문서가 실제로 46건 발견됐고 수집은 완전했지만, 신규 페이지 구조 하나가 정규화 승격을 막았다”는 운영 실패 지점을 측정한 것이다.
