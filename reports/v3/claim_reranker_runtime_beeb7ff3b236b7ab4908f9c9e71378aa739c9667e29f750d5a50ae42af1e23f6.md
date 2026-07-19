# DNF RAG v3 claim-aware evidence reranker

## 결과

- adaptive dev rows: 63
- baseline cited evidence groups: 47/59
- reranked cited evidence groups: 57/59
- strict improvements: 10
- strict regressions: 0
- moved top evidence: 10
- verified claims: 59/59
- policy violations: 0

## 판정

- claim_aware_reranker_adaptive: **GO**
- reranked_runtime_integration: **GO**
- strict_59_of_59_quality: **NO-GO**
- production_evidence_selector: **NO-GO**
- final_benchmark: **NO-GO**

## 남은 strict mismatch

- 비인가 프로그램 사용 주의사항은 뭐야? (dnf_notice): acceptable_chunk_not_in_routed_candidates
- 서약 / 결정 사용 방법은 뭐야? (dnf_game_guide): strict_annotation_mismatch_requires_review

gold ID는 runtime reranker 입력에 사용하지 않았고 평가 후에만 대조했다.
이 결과는 adaptive development replay이며 final blind 성능이 아니다.
