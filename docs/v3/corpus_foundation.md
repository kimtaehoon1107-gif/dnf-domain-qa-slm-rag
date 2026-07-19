# DNF RAG v3 코퍼스 기반 설계

## 작업 경계

v2 코드·데이터·인덱스·평가 결과는 동결된 비교 기준선이다. v3 도구는 v2 artifact를 입력으로 읽을 수 있지만 수정하거나 같은 경로에 결과를 쓰지 않는다.

첫 사이클의 범위는 코퍼스 감사와 스키마 확정이다. Router, decomposition, reranker, Generator, Verifier, RAFT/LoRA는 이 사이클에 포함하지 않는다.

## 경로와 artifact 규칙

```text
src/v3/                    v3 실행 코드
data/v3/raw_snapshots/     변경 불가능한 원본 snapshot
data/v3/discovery/         source registry와 discovery 설정
data/v3/normalized/        revision-aware document v3
data/v3/chunks/            chunk v3
data/v3/structured/        이벤트·패치·가격 등 구조화 fact
outputs/v3/indexes/        v3 전용 검색 인덱스
outputs/v3/evaluations/    실행별 원시 평가 결과
reports/v3/               사람이 읽는 감사·비교 보고서
docs/v3/                  결정 기록과 데이터 계약
```

artifact 파일명은 `{stage}_{corpus}_{schema-or-method}_{version}.{ext}` 형태를 사용한다. 예: `documents_dnf_official_v3.0.jsonl`, `chunks_game_guide_heading_v3.0.jsonl`, `corpus_audit_v2_baseline.json`.

인덱스와 평가 결과에는 입력 manifest SHA-256과 실행 설정을 함께 기록한다. `latest` 같은 가변 이름은 canonical artifact로 사용하지 않는다.

## v2 → v3 필드 대응

| v2 | v3 | 처리 |
|---|---|---|
| `doc_id` | `document_id` | legacy ID를 추적 필드에 보존하고 v3 ID 발급 |
| `source_url` | `canonical_url` | URL 정규화 후 저장 |
| `doc_type`, `metadata.official_section` | `source_kind` | 명시적 분류 규칙 적용 |
| `metadata.collected_at` | `fetched_at` | snapshot 시간으로 승격 |
| `effective_start`, `effective_end` | `valid_from`, `valid_to` | 문서 유형별 검증 후 변환 |
| `text` | 원본 본문 | snapshot에는 원문 보존, normalized 단계에서 별도 정제 |
| chunk `text` | `display_text` | 원문 offset으로 재생성 |
| title/heading + `display_text` | `retrieval_text` | 검색 전용 파생 필드 |
| 없음 | revision/hash/status/offset/version | v3에서 신규 생성 |

## 스키마 계약

런타임 필드 계약은 `src/v3/schemas.py`의 `DocumentV3`, `ChunkV3`가 canonical이다. nullable 필드도 키 자체는 반드시 존재해야 한다.

핵심 불변식:

- snapshot은 덮어쓰지 않는다.
- 동일 URL의 내용 hash가 바뀌면 새 revision을 만든다.
- `display_text`는 원문 substring이고 `start_offset:end_offset`으로 재현되어야 한다.
- `retrieval_text`는 인용에 사용하지 않는다.
- 만료·대체 문서는 삭제하지 않고 status와 revision 관계로 필터링한다.
- 구조화 fact는 `source_document_id`와 `evidence_chunk_id` 없이 배포하지 않는다.

## 첫 감사 실행

```powershell
python -m src.v3.audit_corpus
python -m unittest tests.v3.test_audit_corpus
```

감사 결과는 `reports/v3/corpus_audit_v2_baseline.json`과 `.md`에 생성된다. 공식 사이트 전체 대비 수집률은 별도의 URL discovery snapshot이 없으면 `not_measured`로 유지한다.

## 다음 A/B 전에 필요한 게이트

1. URL discovery snapshot과 raw snapshot manifest를 만든다.
2. document v3 변환 후 필수 키, hash, revision, category, validity 검사를 통과한다.
3. chunk v3에서 offset round-trip 100%, 빈 청크 0, orphan 0을 달성한다.
4. 문서 유형별 chunker를 한 종류씩 v2와 비교한다.
5. 그 뒤에만 독립 BM25 후보군을 구현하고 candidate recall을 측정한다.

## 두 번째 사이클: snapshot과 revision 기반

두 번째 사이클에서는 v2 raw를 byte-for-byte 보존한 snapshot, 재현 가능한 corpus manifest, revision-aware `DocumentV3` metadata artifact까지 구현한다. 세부 스키마·명명·hash·ID·status 규칙은 [raw_snapshot_and_revision_contract.md](raw_snapshot_and_revision_contract.md)를 canonical 결정 기록으로 사용한다.

이 단계에서는 본문 parser를 새로 만들거나 chunk를 생성하지 않는다. BM25, Router, decomposition, Evidence Selector, Generator, Verifier, RAFT/LoRA도 범위 밖이다.

## 세 번째 사이클: 공식 출처 discovery와 coverage

다음 사이클의 첫 구현은 parser나 대량 detail 수집이 아니라 공식 출처의 URL discovery registry와 coverage report다. 확정 source, 수집 기간, store mapping, 기본 검색 제외 정책, coverage 집합 정의는 [source_discovery_registry.md](source_discovery_registry.md)를 따른다.

URL discovery 결과를 검토해 수집 누락과 분류 불확실성을 확인하기 전에는 문서 유형별 detail parser와 chunker로 넘어가지 않는다. BM25는 계속 `ChunkV3` 검증 뒤의 단계로 둔다.
