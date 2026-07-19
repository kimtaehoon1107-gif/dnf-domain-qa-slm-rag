# DNF RAG v3 claim reranker canonical audit

## 판정

- 재현 가능한 canonical: **v3.1 56/59**, strict regression 0
- v3.2 57/59: **development-only**, artifact 보존, 승격 안 함
- shared immutable input mismatch: **0**
- 실제 citation 선택 변경: **1건**

동일한 문서·청크·dev·baseline runtime·BGE·temporal overlay에서 source code와
evaluator code만 달랐다. 선택이 달라진 질문은 `세라샵 아이템 청약철회는 구입 후 며칠 안에 문의해야 하고, 언제 불가능해?`이다.
canonical source SHA-256은 manifest와 정확히 일치하고 cases/manifest replay도
동일하다. v3.2는 canary 일반화 확인 전까지 canonical로 사용할 수 없다.
