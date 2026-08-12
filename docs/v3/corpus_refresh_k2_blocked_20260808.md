# 코퍼스 갱신 K2 중단 보고

작성일: 2026-08-08

## 결론

중첩 `img` 파서 수정과 998건 재검증은 통과했지만, `corpus_refresh_round_plan.md`의 K2 정규화 단계에서 현재 노출 중인 이미지 의존 문서 2건에 대한 시각 근거 또는 제외 overlay가 없음을 발견했다. 정규화 빌더의 안전 계약에 따라 즉시 중단했다.

따라서 다음 작업은 청킹이나 인덱싱이 아니라 **두 문서의 시각 근거 판정**이다. K2가 완료되지 않았으므로 K3 GPU 확인·BM25/BGE-M3 인덱싱·런타임 상수 전환·Qwen adaptive 재실행은 모두 수행하지 않았다.

## 고정 입력

- `built_at`: `2026-08-07T19:12:13+09:00`
- registry: `data/v3/discovery/source_registry_4c5ff1fb05f9d2eb9962caa03f87a09190950291d1338eeae579c2ae0f292ff1.jsonl`
- ledger: `data/v3/collections/detail_full_collection_ledger_a9230fa5c2a8f70df77749db7bf37a0a307506d27fa25d588c9310accacc1a6f.jsonl`
- hardened preview: `data/v3/collections/detail_hardened_extraction_preview_72e6787ffafbb0847a41588f994435dbccfeede5214788bd7ef82276a56fb27c.jsonl`
- visual evidence: `data/v3/visual_evidence/visual_document_evidence_c7362de31d59ee1f0877477caa8c5d4848fdbdf40719b5c64cdb861c29469d38.jsonl`
- correction overlay: `data/v3/visual_evidence/discovery_correction_overlay_0841fdad1f8c80dcda51036162b524ed4c7cf3cd31fb2bdb26a915cf77ddf61b.jsonl`
- visual manifest: `data/v3/visual_evidence/visual_evidence_manifest_ff585eb897627edd9bceae3f643fe5ac23904a07fcbed7b5fbe51cb59e64050b.json`
- baseline DocumentV3: `data/v3/normalized/documents_dnf_official_v3.0_c77299d729a6.jsonl`

원문 998건을 다시 수집하지 않았고, P2에서 생성한 hardened preview를 그대로 사용했다.

## 입력 계약 확인 과정

처음에는 현재 런타임의 v3.1 DocumentV3를 baseline으로 명시했으나, 이 파일에는 동일 URL의 보존 revision이 여러 행 존재해 빌더의 `baseline URL 1개당 1행` 계약에 맞지 않았다.

```text
RuntimeError: Duplicate canonical URL in baseline DocumentV3:
https://df.nexon.com/guide?no=1535
```

이 실행은 입력 검증에서 종료돼 artifact를 만들지 않았다. 코드 기본값과 기존 정상 빌드 계약을 대조해 canonical v3.0 baseline으로 정정한 뒤 다시 실행했다.

## K2 실제 중단 원인

정정된 입력으로 실행하자 다음 안전 게이트에서 종료됐다.

```text
RuntimeError: Eligible URL has no normalization path or overlay:
https://df.nexon.com/pg/21stspecialmission
```

동일한 조건을 전체 eligible URL에 적용해 waterfall을 확인한 결과 blocker는 2건이다.

| URL | 제목 | DOM 추출 | 이미지 의존 판정 | 시각 근거 | overlay |
|---|---|---:|---|---|---|
| `https://df.nexon.com/pg/21stspecialmission` | 21st Special Mission | parsed, 8,311자 | high, 이미지 290개 | 없음 | 없음 |
| `https://df.nexon.com/pg/michaela` | 21st Anniversary | parsed, 270자 | high, CSS 자산형 이벤트 페이지 | 없음 | 없음 |

두 문서는 모두 registry에서 `status=current`, `default_exposure=true`다. hardened parser 자체는 두 문서를 정상 파싱했지만, 다음 이유로 `normalization_eligible=false`다.

- `21stspecialmission`: `low_text_per_image_without_table`, `image_content_not_ocr`
- `michaela`: `custom_event_short_dom_text_or_css_assets`

기존 시각 근거와 correction overlay는 2026-07-17 snapshot에 대응하며 위 두 URL을 포함하지 않는다. 이를 무시하고 DOM 텍스트만 정규화하면 이미지에 있는 핵심 내용을 누락할 수 있으므로 빌더 차단이 옳다.

## 게이트 판정

| 단계 | 판정 | 근거 |
|---|---|---|
| P0 수정 전 재현 | PASS | 새 회귀 1건이 예상 예외로 실패 |
| P1 최소 수정 | PASS | 2줄 변경, 새 회귀 통과, 기존 SHA 실패 2건만 유지 |
| P2 998건 재검증 | PASS | parser failure 0, 비대상 994/994 동일, 중첩 정상 문서 4/4 SHA 동일 |
| K2 정규화 | **BLOCKED** | 현재 이미지 의존 문서 2건의 시각 근거/overlay 누락 |
| K2 봉인 청크 33/33 | 미실행 | 정규화 artifact가 생성되지 않아 청킹하지 않음 |
| K3 이후 | 미실행 | K2 실패 시 즉시 중단 규칙 적용 |

## 다음에 필요한 별도 작업

기존 raw snapshot을 유지한 채 위 두 URL만 시각 검수해야 한다.

1. 화면에 의미 있는 텍스트/표가 있으면 검증된 visual evidence를 추가한다.
2. 수집 대상이 아니거나 안전하게 정규화할 수 없으면 근거를 남긴 correction overlay로 제외한다.
3. 새 visual manifest를 고정한 뒤 동일 `built_at`과 기존 registry/ledger/hardened preview로 K2를 다시 시작한다.

어느 판정도 하지 않은 상태에서 `normalization_eligible`을 강제로 바꾸거나, 빈 시각 근거를 합성하거나, K3로 우회해서는 안 된다.
