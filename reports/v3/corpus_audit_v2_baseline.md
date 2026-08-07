# DNF RAG v3 코퍼스 감사 — v2 기준선

> v2 원본과 canonical 청크를 읽기 전용으로 감사한 결과다. 이 보고서는 v3 코퍼스 변환 결과가 아니다.

## 입력 artifact

| 경로 | SHA-256 |
|---|---|
| `data/raw/guide_docs.jsonl` | `c1049eb0d8c1910d99abe6ad345af21b7820e5f3a483a6836342ad332daeb613` |
| `data/raw/official_docs.jsonl` | `4a9ad194cd3c285c2ffd4d61b29e9ca1422117b28a1759f7d354075f5869f307` |
| `data/processed/domain_doc_chunks.jsonl` | `40c4437034352331209430751a7568bc2da8620764587f65ae8a758a543ce3da` |

## 핵심 통계

| 항목 | 값 |
|---|---:|
| 부모 문서 | 188 |
| 게임 가이드 문서 | 125 |
| 패치노트 문서 | 20 |
| 이벤트 문서 | 23 |
| 공지 문서 | 13 |
| 계정·결제 정책 문서 | 5 |
| 알려진 문제 문서 | 2 |
| 청크 | 1307 |
| 청크 길이 중앙값 | 262.0자 |
| 100자 미만 청크 | 192 |
| 200자 미만 청크 | 504 |
| 동일 텍스트 청크 그룹 | 11 |
| 동일 텍스트 그룹 소속 청크 | 31 |
| 원문 offset 보유 청크 | 0 / 1307 |
| orphan 청크 | 0 |

## 문서 메타데이터

- category 누락: 111 / 188
- 가이드 category 누락: 111 / 125
- 가이드 갱신일 누락: 44 / 125
- 유효기간 필드가 하나라도 있는 문서: 22 / 188

## 발견된 문제

| 심각도 | 검사 | 건수 | 설명 |
|---|---|---:|---|
| not_measured | `source_discovery_coverage` | 측정 불가 | 수집 시점의 공식 사이트 URL 발견 목록이 없어 사이트 전체 대비 수집률을 계산할 수 없음 |
| warning | `missing_document_category` | 111 | 문서 유형별 category_path 보강 필요 |
| warning | `missing_guide_updated_at` | 44 | 가이드 revision 판정에 필요한 갱신일 누락 |
| warning | `missing_validity` | 166 | valid_from/valid_to/status를 문서 유형별로 판정해야 함 |
| warning | `duplicate_chunk_text` | 31 | 동일 normalized text 청크가 여러 ID로 존재함 |
| warning | `short_chunks_under_200` | 504 | 고립 여부와 형제 병합 가능성 검토 필요 |
| error | `missing_chunk_offsets` | 1307 | 원문 위치 역추적 불가 |

## 해석

- v2 artifact는 기준선 비교용으로 유지하며 이 입력 파일들을 수정하지 않는다.
- 첫 v3 변환은 snapshot/revision/hash를 먼저 만들고, 그 뒤 문서 유형별 parser와 chunker를 적용한다.
- 사이트 전체 대비 수집률은 URL discovery snapshot이 생기기 전에는 정직하게 측정 불가로 둔다.
- Router, Evidence Selector, 학습은 corpus 및 independent BM25 후보 recall이 검증된 뒤 진행한다.
