# DNF RAG v3 schema-constrained extractive Generator/Verifier pilot

## 결과

- answer plans: 4
- claims: 8
- verified plans: 4/4
- cited evidence groups: 8/8
- minimum gold-span token recall: 0.7037
- maximum claim chars: 75

## 판정

- answer_plan_contract: **GO**
- schema_constrained_extractive_generator: **GO**
- deterministic_claim_verifier: **GO**
- natural_language_generator: **NO-GO**
- production_nli_verifier: **NO-GO**
- final_benchmark: **NO-GO**

claim은 cited ChunkV3의 연속 원문 구절이며 자유 생성이나 paraphrase가 아니다.
이 결과는 adaptive development pilot이며 final blind 성능이 아니다.
