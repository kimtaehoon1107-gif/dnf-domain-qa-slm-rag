# DNF RAG v3 claim-aware evidence reranker

이 단계는 동결된 unified adaptive runtime의 route-filtered 후보만 재정렬한다.
기존 검색·Router·시간 필터와 baseline artifact는 변경하지 않는다.

## 입력과 금지 사항

- runtime 입력은 질문, route를 통과한 선택 후보, 기존 BGE relevance 점수뿐이다.
- `acceptable_chunk_ids`, `evidence_span`, gold answer는 재정렬 후 평가에만 사용한다.
- BGE 점수는 문서 관련도 보조 신호다. 기존 1위보다 0.30 이상 높고 절대점수
  0.80 이상일 때만 강한 override를 허용한다.
- 그 외 순위 변경은 질문 숫자 리터럴, 복합 필수 필드, 대응 행동 구절 또는 큰
  lexical coverage 개선이 있을 때만 허용한다.

## claim과 검증

후보별로 최대 700자의 연속 원문 구절을 선택한다. 최종 claim은 canonical
ChunkV3 `display_text`에 그대로 존재해야 한다. Verifier는 citation parent,
route source, current/default 노출, document revision을 검사한다. current
운영정책은 temporal overlay의 `is_current_revision=true` 문서와 일치해야 한다.

`partial` 질문은 공식 사실만 제시한다는 disclaimer를 유지하며 `reject`와
`realtime_api`는 근거를 노출하지 않는다.

## 승격 기준

adaptive reranker GO는 63개 재생, 검증 claim 59개, 시간·출처 위반 0,
false-route 근거 노출 0, 기존 strict citation 회귀 0과 개선 양수를 요구한다.

production 승격은 별도다. strict 59/59, 남은 대체 근거 사람 판정, 독립 holdout이
모두 필요하다. 이 adaptive 결과를 final benchmark 성능으로 부르지 않는다.
