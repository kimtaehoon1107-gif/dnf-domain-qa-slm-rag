# DNF RAG v3 decomposed hybrid retrieval 계약

## 범위

Question Decomposition 파일럿에서 확정한 4개 adaptive dev 부모 질문과 8개 하위
질문을 promoted BGE-M3 0.75/BM25 0.25 hybrid runtime으로 검색한다. Generator,
claim 생성, 최종 blind 평가는 수행하지 않는다.

## 하위 질문 검색

- 각 하위 질문은 Question Router를 다시 통과한다.
- source ID와 source kind를 먼저 제한한 뒤 hybrid top-10을 계산한다.
- 운영정책은 Temporal Policy가 선택한 revision 문서만 검색한다.
- `YYYY년 M월 당시` 형태의 과거 질문은 해당 달과 `valid_from`/`valid_to`가
  겹치는 문서만 검색한다. 유효기간이 모두 없는 문서는 과거 월 검색에서 제외한다.
- current 질문은 `current/upcoming`, `default_exposure=true`,
  `review_required=false`만 허용한다.

과거 월 창은 검색 후보를 제한하는 메타데이터이며 작성일 최신성 가중치가 아니다.

## Evidence merge

Evidence Selector를 하위 질문별로 적용한 뒤 정확히 같은 `chunk_id`만 중복 제거한다.
중복 제거된 근거에도 모든 `subquestion_id`, child ordinal, time scope와 원래 rank를
보존한다. 서로 다른 하위 질문의 quota를 전역 점수로 다시 경쟁시키지 않는다.

같은 `lineage_id`에서 여러 `revision_id`가 발견되면 다음처럼 처리한다.

- current와 historical 슬롯이 명시적으로 분리되었거나 comparison route이면 둘 다 보존
- 그 외에는 `blocked_revision_conflict`로 처리하고 병합 근거를 Generator에 전달하지 않음
- source/time/default exposure 위반도 `blocked_policy_violation`으로 차단

## 평가 경계

Gold chunk ID와 evidence span은 검색·필터·병합 입력으로 사용하지 않는다. 모든 처리가
끝난 뒤 hybrid top-10, selected evidence, merged evidence의 evidence-group coverage를
감사할 때만 사용한다. hybrid GO에는 직전 BM25 child top-10 대비 evidence-group
coverage 비회귀도 포함한다. 이 결과는 adaptive development pilot이며 final benchmark가
아니다.
