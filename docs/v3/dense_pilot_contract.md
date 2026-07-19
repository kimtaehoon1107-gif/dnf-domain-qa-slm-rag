# DNF RAG v3 BGE-M3 dense index 파일럿 계약

## 범위와 판정

ChunkV3 파일럿에서 승인된 63개 부모 문서에 해당하는 full-corpus ChunkV3 467개를 BGE-M3로 실제 임베딩하고, BM25와 동일한 검색 필터 및 title/control diagnostic을 검증했다.

- dense pilot version: `dnf_bge_m3_dense_pilot_v3.1`
- model: `BAAI/bge-m3`
- model revision: `5617a9f61b028005a4858fdac845db406aefb181`
- SentenceTransformers: `5.5.1`
- PyTorch: `2.11.0+cu128`
- device: `NVIDIA GeForce RTX 5070 Laptop GPU`
- requested max sequence length: 2,048
- embedding dimension: 1,024
- fixed `built_at`: `2026-07-18T01:51:13+09:00`
- full dense index 진입 판정: **GO**

이 사이클에서는 전체 3,599개 임베딩, persistent vector DB, hybrid 승격, Router, decomposition, generator, verifier, 학습을 실행하지 않았다.

## 결정론적 선택

입력은 canonical ChunkV3 3,599개와 기존 content-addressed 63-document pilot selection이다. 부모 `document_id`를 결합한 뒤 `chunk_id`로 정렬한다.

- documents: 63
- chunks: 467
- DOM chunks: 445
- visual OCR chunks: 22
- default exposure chunks: 272
- sources: 8
- statuses: current, expired, superseded, unknown

선택 JSONL에는 각 chunk의 parent/source/status/exposure/review/offset source와 `retrieval_text` SHA-256을 기록한다.

## Embedding artifact

`retrieval_text`를 `max_seq_length=2048`, batch size 2로 임베딩했다. 결과는 L2-normalized float32이며 cosine similarity는 normalized dot product로 계산한다.

Matrix는 metadata의 `ordinal` 순서와 같은 C-order little-endian float32 raw bytes다.

- shape: `[467, 1024]`
- finite values: 전체 통과
- norm min: `0.9999999403953552`
- norm max: `1.0000001192092896`
- non-unit rows at tolerance `1e-5`: 0

Metadata는 ordinal, chunk/parent ID, canonical URL, title, source, status, exposure, review, validity를 포함한다. 검색 결과를 원문과 연결할 때 embedding ordinal과 metadata ordinal을 반드시 함께 검증한다.

## Token 길이와 truncation

임베딩 전에 같은 model tokenizer로 truncation 없이 길이를 측정했다.

| metric | tokens |
|---|---:|
| min | 54 |
| p50 | 225 |
| p90 | 856 |
| p95 | 902 |
| p99 | 1,032 |
| max | 1,113 |

- 2,048 초과: 0
- truncation detected: false

따라서 현재 파일럿에서 `max_seq_length=2048`은 충분하다. 전체 3,599개에서도 이전 측정 최대가 1,187이었지만, full dense build는 임베딩 직전 동일 검사를 다시 수행해야 한다.

## 필터 parity

Dense 검색은 BM25의 `SearchPolicy`를 그대로 사용한다.

- 기본: `default_exposure=true`
- 기본 status: current/upcoming
- 기본 OCR/review 제외
- `as_of`가 있으면 validity 경계 적용
- expired, superseded, preview, OCR은 명시적 opt-in에서만 허용

기본 필터 parity mismatch와 diagnostic default policy violation은 모두 0이다.

## BM25 대비 diagnostic

동일 467개 후보와 동일 query/filter로 비교했다.

- dense default title hit@5: 8/8
- BM25 default title hit@5: 8/8
- dense historical/OCR control hit@5: 4/4
- BM25 historical/OCR control hit@5: 4/4
- dense default policy violation: 0
- 평균 top-5 chunk overlap: `0.516667`

Title/control diagnostic은 배관 검증이다. 자연어 질문 retrieval 품질이나 dense 우월성을 입증하지 않는다. Top-5 overlap이 약 0.52이므로 두 검색기가 실제로 다른 후보를 내며, 근거 라벨이 있는 retrieval dev gate 없이 hybrid로 합치면 안 된다.

## 수치 재현성

같은 프로세스에서 앞 16개를 다시 encode했을 때 최대 절대 차이는 `1.7695128917694092e-07`이었다. 허용치 `1e-6`은 통과하지만 bitwise 동일하지는 않다.

- 이미 동결된 float32 matrix bytes를 다시 freeze하면 동일 SHA-256이 재현된다.
- GPU에서 모델을 다시 encode하면 같은 software/device에서도 미세한 부동소수점 차이로 새 SHA-256이 생길 수 있다.
- full dense build는 model revision, software, device, dtype, normalization, max length, batch size를 manifest에 기록하고 수치 허용치와 content hash를 함께 사용해야 한다.

## Canonical artifacts

- selection: `data/v3/indexes/dense_pilot_selection_fdfdde3e765a5e68a093127f235f6d5e41168ea9c8e0d54f60ea74fe121c1e8e.jsonl`
- metadata: `data/v3/indexes/dense_pilot_metadata_948948873ff42c11abd194f6d13a2b2dc3abde06db199ab5e98afcd9b7337c89.jsonl`
- embeddings: `data/v3/indexes/dense_pilot_embeddings_3d75d86d51c5f7ff4a00c09526932d4ada5eac88ed1b9505b6e55c9259d48a15.f32`
- manifest: `data/v3/indexes/dense_pilot_manifest_3494f45113fe2f0e077becc3c905893d07869e4c1cb922511872676aec6d4438.json`
- diagnostics: `data/v3/retrieval/dense_pilot_diagnostics_0f79f78369115feeed1773573b2f771039761929db2bec0cf158321df43dacea.jsonl`
- report: `reports/v3/dense_pilot_f1640c1117d7a7d210fdb56be4b1d13898f8c81a46b0c8e63f77280e67b36db9.json` 및 `.md`

각 JSON/JSONL/binary 파일명의 suffix는 해당 파일 bytes의 SHA-256이다.

## 다음 단계

전체 3,599개 BGE-M3 dense artifact 생성 진입은 **GO**다. 다음 사이클은 full embedding matrix와 metadata/manifest freeze, 전체 filter parity, token truncation, norm, ordinal alignment 감사까지만 수행한다. Dense-vs-BM25 품질 승격과 hybrid/Router는 근거 라벨을 가진 v3 retrieval dev set이 생긴 뒤 별도 판정한다.
