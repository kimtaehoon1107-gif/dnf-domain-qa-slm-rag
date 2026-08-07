# DNF RAG v3 raw snapshot·DocumentV3 빌드 보고서

## 범위

두 번째 코퍼스 사이클에서 v2 raw artifact를 읽기 전용 입력으로 사용해 다음까지만 수행했다.

1. byte-for-byte immutable raw snapshot
2. content-addressed corpus manifest
3. canonical URL·content hash 기반 revision-aware `DocumentV3` metadata artifact
4. 스키마·hash·ID·입력 불변성·revision 관계 검증

chunker, BM25, Router, decomposition, Evidence Selector, Generator, Verifier, RAFT/LoRA는 실행하지 않았다. 기존 frozen blind도 사용하지 않았다.

규칙의 canonical 기록은 `docs/v3/raw_snapshot_and_revision_contract.md`다.

## 입력 불변성

| v2 입력 | 변경 전 SHA-256 | 빌드 후 SHA-256 | 결과 |
|---|---|---|---|
| `data/raw/guide_docs.jsonl` | `c1049eb0d8c1910d99abe6ad345af21b7820e5f3a483a6836342ad332daeb613` | `c1049eb0d8c1910d99abe6ad345af21b7820e5f3a483a6836342ad332daeb613` | 동일 |
| `data/raw/official_docs.jsonl` | `4a9ad194cd3c285c2ffd4d61b29e9ca1422117b28a1759f7d354075f5869f307` | `4a9ad194cd3c285c2ffd4d61b29e9ca1422117b28a1759f7d354075f5869f307` | 동일 |

snapshot은 각 원본과 파일 크기와 SHA-256이 모두 같아 byte equality를 확인했다.

## 생성 artifact

| artifact | 행 | bytes | SHA-256 |
|---|---:|---:|---|
| `data/v3/raw_snapshots/raw_snapshot_guide_docs_v2_c1049eb0d8c1.jsonl` | 125 | 893,815 | `c1049eb0d8c1910d99abe6ad345af21b7820e5f3a483a6836342ad332daeb613` |
| `data/v3/raw_snapshots/raw_snapshot_official_docs_v2_4a9ad194cd3c.jsonl` | 63 | 466,221 | `4a9ad194cd3c285c2ffd4d61b29e9ca1422117b28a1759f7d354075f5869f307` |
| `data/v3/raw_snapshots/corpus_manifest_dnf_official_v3.0_c77299d729a6.json` | - | 1,392 | `3f03c720f64eccad34824c227af98558dab4812e49b95f0dcda25290f617d52f` |
| `data/v3/normalized/documents_dnf_official_v3.0_c77299d729a6.jsonl` | 188 | 157,447 | `a202b31bbccf8433f7eb260ce14d449868c8e8815b42b19696468977b529daf3` |

manifest ID:

```text
manifest_sha256_c77299d729a62607e115c3d6ad60f98fef550bd7b1d299246368c8ce67e1de7d
```

## 정규화 결과

| 검사 | 결과 |
|---|---:|
| raw 관측 행 | 188 |
| `DocumentV3` 행 | 188 |
| 고유 canonical URL | 188 |
| 고유 `document_id` | 188 |
| 고유 `revision_id` | 188 |
| 같은 URL·같은 content 중복 관측 | 0 |
| 같은 URL·다른 content revision 관계 | 0 |
| 빈 `category_path` | 0 |
| `supersedes_document_id` 보유 행 | 0 |
| snapshot 시점 `current` | 188 |

현재 입력에는 같은 canonical URL이 없으므로 실제 코퍼스에서 revision chain이 발생하지 않은 것이 정상이다. 같은 URL의 동일 content dedup과 변경 content의 `supersedes_document_id` 연결은 synthetic 단위 테스트로 검증했다.

`status`는 빌드 실행일이 아니라 각 snapshot의 `fetched_at` 기준이다. 따라서 위의 `current` 188건은 2026-07-05 수집 시점 판정이며, 현재 질의 시점의 이벤트 활성 여부를 의미하지 않는다.

## 검증

| 검증 | 결과 |
|---|---|
| manifest 필수 키 | pass |
| snapshot entry 필수 키 | pass (2/2) |
| `DocumentV3` 필수 키 | pass (188/188) |
| snapshot SHA-256과 manifest 일치 | pass |
| raw payload → content hash round-trip | pass (188/188) |
| 같은 build 2회 실행 경로·SHA-256 일치 | pass |
| 기존 감사 + 신규 build 단위 테스트 | pass (5 tests) |
| `python -m compileall -q src/v3 tests/v3` | pass |

신규 단위 테스트가 직접 확인하는 항목:

- 필수 manifest·snapshot entry·`DocumentV3` 키
- content hash 재현성
- 반복 build의 manifest/document SHA-256과 ID 안정성
- v2 입력 byte/hash 불변성
- URL canonicalization
- 같은 URL·같은 content dedup
- 같은 URL·다른 content revision과 supersedes 연결

## 알려진 한계

- v2 수집기 자체 parser version은 기록돼 있지 않아 `legacy-v2-unversioned`로 정직하게 표시했다.
- legacy `collected_at`에는 timezone이 없어 원문 값을 보존했으며 timezone을 추정하지 않았다.
- URL discovery snapshot이 없어 공식 사이트 전체 대비 source coverage는 계속 측정 불가다.
- 상세 가이드 category가 없던 행은 `['guide']`까지만 보존하며 누락 category를 추정하지 않았다.
- 이번 artifact는 metadata envelope다. 본문 parser·표/이미지 보존·offset round-trip·ChunkV3는 아직 검증하지 않았다.
- 실제 입력에 과거 revision 사례가 없어 revision chain의 실데이터 검증은 다음 변경 snapshot이 생긴 뒤 다시 해야 한다.

## 승격 판정

**raw snapshot·manifest·DocumentV3 기반 단계는 PASS**다. 후속 범위가 구체화됨에 따라 다음 사이클의 첫 구현은 `docs/v3/source_discovery_registry.md`에 고정한 공식 출처 URL discovery registry와 coverage report다. 발견 URL과 누락 범위를 검토한 뒤에만 문서 유형별 본문 정규화와 `ChunkV3` offset round-trip으로 진행한다.

**BM25 단계로는 아직 NO-GO**다. `ChunkV3`의 원문 offset round-trip 100%, 빈 청크 0, orphan 0, 문서 유형별 chunker A/B가 완료되지 않았다. Router 이후 단계와 학습도 계속 보류한다.
