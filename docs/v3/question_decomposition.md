# DNF RAG v3 Question Decomposition 파일럿 계약

## 범위

Question Router가 `needs_decomposition=true`로 판정한 질문만 분해한다. 단일 사실 질문,
운영정책 Temporal Router가 직접 처리하는 revision 비교 질문에는 적용하지 않는다.

이번 파일럿은 adaptive retrieval dev의 다중 근거 질문 4건을 대상으로 하며 다음 세
문장 구조만 지원한다.

- 두 월의 동일 항목을 각각 묻는 `month_pair`
- 두 상품의 공통 속성을 비교하는 `shared_attribute_comparison`
- 이미 독립적인 두 절을 연결한 `paired_clauses`

지원하지 않는 구조는 임의로 분할하지 않고 실패한다.

## 하위 질문 계약

각 하위 질문은 다음을 가져야 한다.

- 원 질문과 순서를 추적하는 안정적인 `subquestion_id`
- 독립적으로 검색 가능한 한 가지 사실 요청
- 비교 항목의 좌우 또는 첫째·둘째 관계
- `current`, `historical`, `inherit_parent` 시간 힌트

생성된 하위 질문은 다시 Question Router에 들어간다. child Router가 다시
`needs_decomposition=true`를 반환하거나 clarification을 요구하면 파일럿 실패다.

월 비교에서는 실행 기준 월과 같은 월은 current로, 다른 월은 연도를 복원한 명시적
historical 질문으로 만든다. 예를 들어 2026-07-18 기준 `7월과 6월`은 7월 current와
2026년 6월 historical로 분리한다.

## 검색 및 평가

이 파일럿은 child route 이후 BM25 top-10까지만 검증한다. 각 child가 한 evidence
group을 검색하고 모든 parent evidence group의 합집합을 덮어야 한다.

gold document/chunk ID와 evidence span은 분해 규칙이나 child Router 입력으로 사용하지
않고, 모든 처리 후 hit coverage를 감사할 때만 사용한다. 평가 세트는 adaptive dev이며
final blind가 아니다.

## 승격 경계

이 사이클의 GO는 결정론적 분해, child source/time 재라우팅, BM25 evidence pilot까지만
의미한다. child hybrid retrieval, 결과 병합, 충돌 해결, Generator, Verifier, 최종
benchmark는 포함하지 않는다.
