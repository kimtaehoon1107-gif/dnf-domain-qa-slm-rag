# DNF RAG v3 Hybrid Fusion 실험 계약

## 범위

frozen BM25/dense top-20 검색 결과의 합집합만 사용해 score-level hybrid를 측정한다. 질문 재임베딩, 새 수집, Router, decomposition, generator, verifier, 학습, frozen blind 평가는 수행하지 않는다.

이 실험은 작은 retrieval dev 55개 answerable/partial 문항에서 후보 방식을 비교하는 개발 단계다. 최선 설정도 승격 gate를 모두 통과하기 전에는 canonical 검색 기본값이 아니다.

## Fusion 규칙

- 입력 후보: 문항별 BM25 top-20과 dense top-20 합집합
- 정규화: 문항별·검색기별 min-max score normalization
- 다른 검색기에 없는 후보의 해당 score: 0
- 결합: `(1 - dense_weight) × bm25_normalized + dense_weight × dense_normalized`
- 동점: `chunk_id` 오름차순
- 고정 grid: dense weight 0.25, 0.50, 0.75

가중치는 실행 후 추가하거나 미세 조정하지 않는다. 제한된 고정 grid만 비교해 63개 개발 문항에 대한 과적합을 줄인다. v2에서 비채택됐던 RRF는 이번 실험에 다시 포함하지 않는다.

## 선택과 승격 gate

개발 세트의 최선 설정은 hit@10, all-groups@10, evidence-group recall@10, MRR 순으로 결정한다. 그러나 hybrid 승격은 dense 단독과 비교해 다음을 모두 만족해야 한다.

1. hit@10 엄격 개선
2. all-groups hit@10 엄격 개선
3. evidence-group recall@10 엄격 개선
4. MRR 비회귀
5. 출처별 all-groups hit@10 회귀 0
6. 최저 출처 all-groups hit@10 엄격 개선

일부 평균 지표만 좋아진 경우에는 승격하지 않는다.

## 결과

| configuration | MRR | hit@10 | all groups@10 | group recall@10 |
|---|---:|---:|---:|---:|
| dense baseline | 0.6446 | 0.9455 | 0.9273 | 0.9322 |
| dense 0.25 / BM25 0.75 | 0.6838 | 0.9091 | 0.9091 | 0.8983 |
| dense 0.50 / BM25 0.50 | 0.7450 | 0.9455 | 0.9455 | 0.9322 |
| dense 0.75 / BM25 0.25 | 0.7085 | 0.9636 | 0.9455 | 0.9492 |

최선 측정 설정은 `dense_75_bm25_25`다. dense 단독 대비 hit@10, all-groups@10, group recall@10, MRR이 개선됐고 출처별 회귀는 0이다. 그러나 최저 출처인 `dnf_seria_shop`의 all-groups hit@10이 dense와 동일한 0.6667로 남아 최저 출처 엄격 개선 gate가 실패했다.

따라서 실험 무결성은 **GO**, hybrid 승격은 **NO-GO**다. `dense_75_bm25_25`는 진단용 후보이며 canonical 기본값으로 승격하지 않는다.

## Frozen artifacts

- per-query grid results: `data/v3/retrieval/hybrid_grid_results_a570e39e37dc6311c5e82fb32d8c403908d3251ba4d6b06babd2857e6b50d9e1.jsonl`
- manifest: `data/v3/retrieval/hybrid_grid_manifest_1e8d64ae1c4deb121333bbf009178668111ad52925438a45b17cda1da1dfadf6.json`
- report: `reports/v3/hybrid_grid_35ac0dbb861207a55bc380bb94dcc92a71defcc7b34e205911c8ee5f5131c093.json`
- readable report: `reports/v3/hybrid_grid_2d827819e42e154c294c8920a51ecd78eb9a53f5c30c6a724480e51372bca364.md`

파일명의 마지막 64자리는 해당 파일 bytes의 SHA-256이다. 같은 frozen 입력을 재평가하면 동일한 네 artifact hash가 나와야 한다.
