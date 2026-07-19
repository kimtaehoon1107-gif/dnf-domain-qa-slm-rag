# DNF RAG v3 전체 eligible 상세 본문 수집

## 범위와 frozen 입력

이 사이클은 discovery registry에서 `eligible_for_collection=true`인 982개 항목의 raw 상세 원문만 수집했다. 최종 DocumentV3 재빌드, ChunkV3, 구조화 store, BM25, Router, 학습은 실행하지 않았다.

- registry: `data/v3/discovery/source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl`
- registry SHA-256: `04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a`
- registry manifest SHA-256: `4cbd8c441fd694ec16ad30b6b42c4c6f28326dc9a768d883399419ef87ee9ea2`
- collector version: `dnf_detail_full_v3.0`
- fixed `fetched_at`: `2026-07-17T21:53:16.6990081+09:00`

선택은 registry 입력 순서와 무관하게 `(source_id, canonical_url)`로 정렬한다. canonical URL 중복은 허용하지 않고, non-eligible row는 포함하지 않는다. 982개 row의 고유 fetch URL은 719개다. FAQ 279개는 synthetic canonical locator를 유지하면서 16개 listing snapshot을 공유한다.

## 실행과 재개 계약

```powershell
python src/v3/collect_details.py --mode full --fetched-at "2026-07-17T21:53:16.6990081+09:00"
```

수집기는 요청 간격, 재시도, 명시적 User-Agent를 적용한다. 각 HTTP 응답은 SHA-256 파일명의 immutable raw snapshot으로 즉시 저장한다. 전체 실행은 다음 append-only checkpoint로 재개할 수 있고, 완료 row는 네트워크로 다시 요청하지 않는다.

- checkpoint: `data/v3/collections/checkpoints/detail_full_checkpoint_a53fa13c1376d056.jsonl`
- checkpoint SHA-256: `8ea0c31861db05426855a914ab32efe71235876656e11db887ec785f6485c4b3`

FAQ는 synthetic URL에 GET하지 않고 registry의 listing URL을 fetch한 뒤 `data-no`를 정확히 선택한다. 운영정책은 요청 revision과 `#revisionList option[selected]` 값이 같은지 검증한다. 이달의 아이템 current endpoint는 canonical identity를 바꾸지 않고 fetch URL에만 trailing slash를 복구한다.

## 수집 결과

| source | selected | success | default exposure 정책 |
|---|---:|---:|---|
| `dnf_account_policy` | 51 | 51 | current 1, superseded 50 비노출 |
| `dnf_event` | 27 | 27 | current 25, expired 2 비노출 |
| `dnf_faq` | 279 | 279 | current 279 |
| `dnf_game_guide` | 125 | 125 | current 125 |
| `dnf_monthly_item` | 14 | 14 | current 1, expired 13 비노출 |
| `dnf_notice` | 396 | 396 | current 396 |
| `dnf_seria_shop` | 72 | 72 | current 30, expired 42 비노출 |
| `dnf_update` | 18 | 18 | live 15, preview 3 비노출 |
| **합계** | **982** | **982** | exposure 위반 0 |

- fetch success / failed / blocked / parser failed: `982 / 0 / 0 / 0`
- 고유 raw snapshot: 719
- 빈 title / 빈 text: `0 / 0`
- FAQ locator 오해결: 0/279
- policy revision 오해결: 0/51
- raw bytes SHA-256 불일치: 0
- default exposure 정책 위반: 0

## 추출 관측

| signal | row 또는 count |
|---|---:|
| heading 포함 row | 703 |
| table 포함 row / table 수 | 385 / 1,441 |
| image 포함 row / image 수 | 741 / 6,521 |
| date metadata row / date signal row | 555 / 671 |
| price signal row | 198 |
| guide baseline 비교 | 125 |

경고가 있는 row는 792개다. `image_content_not_ocr` 741건은 이번 raw 수집의 실패로 보지 않지만, 이미지에 핵심 정보가 있는 문서의 구조화 승격 전 검수 신호로 유지한다.

DocumentV3 승격을 막는 경고는 중복을 제거한 136개 row에 있다.

- `registry_title_not_found_in_selected_content`: 111
- `navigation_or_footer_signal`: 34
- `body_fallback_navigation_risk`: 24 — 모두 custom event page
- `guide_refresh_material_length_change`: 1 — `guide?no=1535`, 기존 806자 대비 1,272자(1.578164배)

운영정책 51건의 title mismatch는 registry의 revision용 합성 제목과 본문 제목 계약 차이일 가능성이 있어 source-specific title 규칙으로 분리해 판정해야 한다. 이벤트 24건은 body fallback을 제거할 전용 selector가 필요하다.

## Canonical artifacts

- ledger: `data/v3/collections/detail_full_collection_ledger_0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b.jsonl`
- ledger SHA-256: `0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b`
- preview: `data/v3/collections/detail_full_extraction_preview_e48f58e205a7001e23e3286cc7df2d467bf8b549f9ce449b82a46a6accf8e1dd.jsonl`
- preview SHA-256: `e48f58e205a7001e23e3286cc7df2d467bf8b549f9ce449b82a46a6accf8e1dd`
- manifest: `data/v3/collections/detail_full_collection_manifest_f3003742b55a515e51c2abaee5a993cea9b1f108297f59c74a9aeaa201f87e97.json`
- manifest SHA-256: `f3003742b55a515e51c2abaee5a993cea9b1f108297f59c74a9aeaa201f87e97`
- report: `reports/v3/detail_full_collection_8dbeef595121a34850e0358de6458999acd603b0252e632a52aec517058c3cd2.json` 및 `.md`
- report JSON SHA-256: `8dbeef595121a34850e0358de6458999acd603b0252e632a52aec517058c3cd2`

manifest는 719개 raw snapshot의 path, content hash, byte count, 참조 수와 checkpoint hash를 전부 기록한다. 같은 checkpoint에서 재freeze하면 ledger, preview, manifest, report hash가 동일하다. 초기 v3.0 full report는 content-addressed 이력으로 남아 있지만, DocumentV3 승격 게이트를 명시한 위 v3.1 report가 canonical이다.

## 판정과 다음 단계

- 전체 eligible raw collection: **GO**
- parser 품질 보강 사이클: **GO**
- 현재 preview를 이용한 DocumentV3 자동 승격: **NO-GO**

다음 사이클은 새 네트워크 대량 수집이 아니라 frozen raw 719개를 입력으로 source-specific parser를 보강한다. 우선순위는 custom event selector, 정책 revision title 규칙, navigation/footer 제거, guide 1건 변화 검수, 이미지 핵심 정보 후보 분류다. 이 게이트가 통과된 뒤 별도 사이클에서 revision-aware DocumentV3를 재빌드한다.
