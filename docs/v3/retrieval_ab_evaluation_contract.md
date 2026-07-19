# DNF RAG v3 BM25·dense 검색 평가 계약

## 범위

frozen retrieval dev 63문항에 canonical BM25와 BGE-M3 dense 검색을 동일한 후보 필터로 적용한다. 정답 근거가 있는 true 47개와 partial 8개, 총 55개만 검색 hit 지표에 포함한다. false 8개는 이후 answerability 평가 입력으로 보존하지만 gold가 없으므로 검색 실패로 계산하지 않는다.

이번 사이클에서는 hybrid 가중치, Router, decomposition, generator, verifier, 학습, frozen blind 평가를 수행하지 않는다.

## 공통 후보 정책

두 검색기는 `SearchPolicy`의 다음 필드를 공유한다.

- `default_exposure_only`
- `allowed_statuses`
- `include_review_required`
- `as_of`

출처 필터는 gold source를 누설하므로 평가에 사용하지 않는다. 각 문항에서 BM25와 dense의 허용 chunk ID 집합이 완전히 같아야 하며, 모든 gold chunk가 해당 후보 집합에 포함돼야 한다. 실제 감사 결과 후보 mismatch와 제외된 gold는 모두 0이다.

## 근거와 지표

overlap 청킹으로 같은 근거가 여러 청크에 존재하면 retrieval dev의 `acceptable_chunk_ids` 중 하나를 찾았을 때 해당 evidence group을 찾은 것으로 판정한다.

- `hit_rate@k`: 필수 group 중 하나 이상을 찾은 문항 비율
- `all_groups_hit_rate@k`: 모든 필수 group을 찾은 문항 비율
- `evidence_group_recall_micro@k`: 전체 필수 group 중 발견된 group 비율
- `evidence_group_recall_macro@k`: 문항별 group recall의 평균
- `MRR`: 가장 먼저 발견된 필수 evidence group의 reciprocal rank 평균

측정 지점은 1, 3, 5, 10, 20이다. multi-evidence 문항은 `hit_rate`만으로 충분하지 않으므로 `all_groups_hit_rate`와 group recall을 함께 본다.

## Dense 재현 계약

- model: `BAAI/bge-m3`
- revision: `5617a9f61b028005a4858fdac845db406aefb181`
- dimension: 1,024
- max sequence length: 2,048
- similarity: normalized dot product

질문 63개의 normalized float32 embedding을 dev row 순서대로 별도 content-addressed binary로 freeze한다. 이 binary를 사용하면 모델을 다시 로드하지 않고 결과·manifest·보고서를 동일 hash로 재생성할 수 있다.

## 실제 결과

| system | MRR | hit@1 | hit@5 | hit@10 | hit@20 | group recall@10 | all groups@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.6149 | 0.4364 | 0.8364 | 0.8727 | 0.9273 | 0.8475 | 0.8545 |
| dense | 0.6446 | 0.4727 | 0.8364 | 0.9455 | 0.9455 | 0.9322 | 0.9273 |

top-10에서 둘 다 성공 46개, BM25만 성공 2개, dense만 성공 6개, 둘 다 실패 1개다. dense가 전체적으로 우세하지만 BM25 고유 성공이 존재하므로 hybrid 실험 진입은 **GO**다. 이는 hybrid 승격을 뜻하지 않는다. 가중치와 결합 방식은 다음 개발 세트 실험에서 별도로 측정해야 하며 현재 hybrid 승격은 **NOT_RUN**이다.

## Frozen artifacts

- query embeddings: `data/v3/retrieval/retrieval_dev_query_embeddings_323c72e8653ffef8fc8edff7135aa7b34d8c5a27efbd27fbaf9fff11f5052442.f32`
- per-query results: `data/v3/retrieval/retrieval_ab_results_c085a45adfff797e13d76ee65aa4d56baf3994532a3fa3d776a6f5d7256f0620.jsonl`
- manifest: `data/v3/retrieval/retrieval_ab_manifest_5d96c252d65aed8632f2a72581641150fe04f04903f283c97cfae29686abc0ca.json`
- report: `reports/v3/retrieval_ab_5c8ebeb3606d785e7c898f32eef036b2fa2f8c8c1dbfbe49957602f23e907550.json`
- readable report: `reports/v3/retrieval_ab_d8debe965e499ca6a1a20a18a27ecd6e631068a205a81571f09de2e7a7d25fcb.md`

파일명의 마지막 64자리는 해당 파일 bytes의 SHA-256이다.
