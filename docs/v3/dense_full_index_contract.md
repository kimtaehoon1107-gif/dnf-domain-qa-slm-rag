# DNF RAG v3 BGE-M3 전체 dense artifact 계약

## 범위와 판정

Canonical ChunkV3 3,599개 전체의 `retrieval_text`를 BGE-M3로 임베딩하고,
행 순서·수치·token truncation·BM25 metadata 및 검색 필터 parity를 감사했다.

- dense full version: `dnf_bge_m3_dense_full_v3.1`
- model: `BAAI/bge-m3`
- model revision: `5617a9f61b028005a4858fdac845db406aefb181`
- max sequence length: 2,048
- batch size: 2
- embedding dtype: little-endian float32
- embedding dimension: 1,024
- built_at: `2026-07-18T11:58:00+09:00`
- 전체 dense artifact 판정: **GO**
- hybrid 승격 판정: **NOT_MEASURED**

이 사이클은 전체 embedding matrix와 metadata/manifest를 freeze한 것이다. 자연어
retrieval 품질 평가, hybrid 결합, Router, decomposition, generator, verifier,
학습은 수행하지 않았다.

## Canonical 입력

- ChunkV3: `data/v3/chunks/chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl`
- ChunkV3 manifest: `data/v3/chunks/chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json`
- DocumentV3: `data/v3/normalized/documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl`
- BM25 manifest: `data/v3/indexes/bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json`
- BM25 index: `data/v3/indexes/bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json`

Builder는 실행 전후에 위 파일의 SHA-256이 동일한지 검사하며 입력을 수정하지
않는다.

## Metadata와 matrix 정렬

Chunk는 `chunk_id`로 정렬하고 metadata의 `ordinal`을 0부터 연속 부여한다.
matrix의 N번째 float32 row는 metadata ordinal N과 정확히 대응한다. Metadata에는
다음 trace 필드를 보존한다.

- chunk/parent ID와 parent content hash
- canonical URL과 title
- source ID/kind, status, exposure, review 상태
- valid_from/valid_to와 offset source
- embedding 입력인 `retrieval_text`의 SHA-256

실제 결과는 다음과 같다.

| documents | chunks | default searchable | visual OCR | matrix |
|---:|---:|---:|---:|---:|
| 980 | 3,599 | 2,527 | 22 | 3,599 × 1,024 |

중복 chunk ID, ordinal mismatch, BM25 chunk ID 차이, BM25 metadata field 차이는 모두
0이다.

## Token과 수치 감사

같은 BGE-M3 tokenizer를 truncation 없이 실행 직전에 측정했다.

| metric | tokens |
|---|---:|
| min | 44 |
| p50 | 252 |
| p90 | 879 |
| p95 | 953 |
| p99 | 1,068 |
| max | 1,187 |

- 2,048 초과: 0
- NaN/Inf: 0
- L2 norm 허용치 `1e-5` 위반: 0
- norm min/max: `0.9999998807907104` / `1.0000001192092896`
- 동일 프로세스 16행 재인코딩 최대 절대 차이: `1.862645149230957e-07`

GPU 재인코딩은 미세한 부동소수점 차이가 생길 수 있으므로 bitwise 동일성을
요구하지 않는다. 이미 생성된 matrix bytes를 다시 freeze하면 동일 SHA-256이
재현되며, 새 encode는 `1e-6` 수치 허용치와 model/software/device provenance로
검증한다.

## BM25 필터 parity

Dense metadata와 BM25 entry를 chunk ID로 결합해 16개 정책을 비교했다.

- 기본 current/upcoming + default exposure + review 제외
- 기준일 `2026-07-18` 적용
- review 포함/제외 전체 상태
- current, expired, superseded, unknown 상태별 조회
- 8개 source ID별 조회

Metadata field mismatch와 filter 결과 mismatch는 모두 0이다. 종료 이벤트·과거
정책·종료 상품·preview/unknown·visual OCR은 기본 검색에 자동 노출되지 않는다.

## Canonical artifacts

- metadata: `data/v3/indexes/dense_full_metadata_0343e23130322d2db046eeb5212f8fe6ca3178456036e1873ca3401634998a46.jsonl`
- embeddings: `data/v3/indexes/dense_full_embeddings_2c294cde018eefa354971029c240dd6fd5f2a30ead757441f6dadacea110b10d.f32`
- manifest: `data/v3/indexes/dense_full_manifest_51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json`
- report: `reports/v3/dense_full_index_4200f191aecd861a9304c9047cf579295f1eec5c195c868df75803dd3948778f.json` 및 `.md`

JSON/JSONL/binary artifact의 파일명 suffix는 해당 파일 bytes의 SHA-256이다.

## 다음 단계

전체 dense artifact 생성은 **GO**다. 다음 사이클은 기존 frozen blind와 분리된
근거 라벨 보유 v3 retrieval dev set을 설계·freeze하는 단계다. Title lookup은
배관 검증일 뿐 자연어 품질 평가가 아니므로, dev set 없이 BM25+dense hybrid를
승격하거나 Router를 시작하지 않는다.
