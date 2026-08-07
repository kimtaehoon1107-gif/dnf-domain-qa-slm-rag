# DNF RAG v3 unified adaptive runtime contract

이 런타임은 adaptive development 63문항에서 Router, 검색, 분해, 근거 선택,
schema-constrained extractive Generator/Verifier를 한 경로로 연결한다. final blind
평가나 자연어 생성 품질 측정은 이 범위에 포함하지 않는다.

## 동작 계약

- `retrieve`: Router의 출처·시간 필터를 적용한 hybrid top-10을 근거 선택기에
  전달한다. 최상위 선택 근거의 연속 원문 구절 하나만 claim으로 만들고 결정론적
  Verifier의 모든 gate를 통과할 때만 노출한다.
- `decompose`: 동결된 4개 복합 질문과 8개 child 검색 결과를 사용한다. child별
  claim과 인용을 유지하고 revision 충돌은 명시적 시간 비교가 아니면 차단한다.
- `reject`, `realtime_api`, `clarify`: corpus hit, 선택 근거, citation을 모두 0개로
  유지한다. 실시간 경로는 정적 문서 답변으로 대체하지 않는다.
- `partial`: 공식 문서로 확인 가능한 사실만 인용하고 개인 계정 판단은 할 수
  없다는 고정 disclaimer를 답변 앞에 붙인다.
- current 질문은 `current`/`upcoming`, `default_exposure=true`만 허용한다.
  과거 정책은 temporal resolver가 선택한 revision과 claim revision이 일치해야 한다.

## 판정 분리

`unified_runtime_integration`은 63개 route·answerability 재현, 55개 검증 응답,
59개 검증 claim, false-route 근거 노출 0, partial disclaimer 8개, 시간·출처 정책
위반 0을 요구한다.

`adaptive_end_to_end_quality`는 더 엄격하게 정답 근거 59개가 검색·선택·인용
각 단계에서 모두 적중하고, 각 claim이 정확히 한 evidence group에 대응하며,
gold span token recall 최솟값이 0.50 이상일 것을 요구한다. 두 판정은 독립적으로
보고하며 adaptive 결과를 final benchmark 성능으로 부르지 않는다.
