# DNF RAG v3 Evidence Reranker A/B

## 범위

고정된 v3 hybrid top-10과 기존 Evidence Selector를 대조군으로 두고 `BAAI/bge-reranker-v2-m3` relevance reranker를 실제 실행했다. 모델 revision은 `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, 최대 길이는 512, batch size는 4다.

이 모델은 entailment 또는 contradiction verifier가 아니다. 이번 결과도 Generator, Router, 학습, 최종 blind 성능을 측정하지 않는다.

## 실험 arm

- baseline: hybrid 점수와 질의 토큰 포괄률 기반 selector
- reranker top-3: reranker 상위 3개
- reranker top-8: reranker 상위 8개
- adaptive 3/8: 기본 top-3, 명시적 다중 근거 표지 또는 저신뢰 질의만 top-8

적응형 arm의 top-8 조건은 다음과 같다.

- 질문에 `각각`, `비교`, `함께` 중 하나가 있음
- reranker 최고점이 0.1 미만

이 조건은 gold chunk·document·source ID를 사용하지 않지만, 현재 dev 관찰로 선택했으므로 독립 holdout 전에는 일반화된 규칙으로 간주하지 않는다.

## 결과

| arm | all-groups hit | group recall micro | 주석 정밀도 | noise | 평균 선택 수 |
|---|---:|---:|---:|---:|---:|
| baseline | 0.981818 | 0.983051 | 0.129754 | 0.870246 | 8.127273 |
| reranker top-3 | 0.945455 | 0.932203 | 0.333333 | 0.666667 | 3.000000 |
| reranker top-8 | 0.981818 | 0.983051 | 0.131818 | 0.868182 | 8.000000 |
| adaptive 3/8 | 0.981818 | 0.983051 | 0.290000 | 0.710000 | 3.636364 |

적응형 arm은 baseline 대비 필수 근거 recall을 유지하면서 주석 정밀도를 `+0.160246` 높였고 평균 선택 수를 `55.2573%` 줄였다.

## 실제 실행 비용

RTX 5070 Laptop GPU에서 answerability가 false가 아닌 55문항의 top-10, 총 550쌍을 실행했다.

- model load: 4.193933초
- batched inference: 19.282104초
- throughput: 28.523859 pairs/sec
- peak CUDA allocation: 2,374,138,368 bytes

이는 전체 평가를 연속 batch로 처리한 throughput이며 온라인 요청의 p50/p95 latency는 아니다.

## 판정

- A/B integrity: GO
- adaptive reranker 개발 후보: GO
- production Evidence Selector: NO-GO
- Generator 진입: NO-GO
- 최종 benchmark: NO-GO

production 승격을 막는 조건은 주석 정밀도 0.5 미달, 의미적 contradiction 미측정, 독립 holdout 미측정, 공지 문항 사람 검토 대기다. 다음 단계는 Generator가 아니라 선택 근거에 대한 entailment/contradiction 판별 가능성을 작은 파일럿으로 검증하는 것이다.

## 고정 산출물

- scores: `data/v3/evidence/evidence_reranker_scores_ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl`
- score manifest: `data/v3/evidence/evidence_reranker_manifest_ad6b3f074d8f6edf848c0129d0ea3d8de1c9438aa3de98dde0bfac0fb7a2f26c.json`
- A/B results: `data/v3/evidence/evidence_reranker_ab_results_49d4e5b75339582c0aad9f6b35bc9d9cb5aa63a671c55ec46de5c023bb04a56f.jsonl`
- A/B manifest: `data/v3/evidence/evidence_reranker_ab_manifest_d0f1a2e89fd98da965af1b8a48687a20b777b60ec24082f003ea73ca6039a1f2.json`
- report: `reports/v3/evidence_reranker_ab_763ca7b93bec87e475a4406f24b7780ebaeadffb7a36b494c473452244d8c90f.json`
