# DNF RAG v3 Temporal Router 계약

## 범위

이 사이클의 Router는 `dnf_account_policy` 운영정책 질문만 대상으로 한다. 범용
Question Router, 자유형 답변 Generator, Verifier를 구현하거나 승격하지 않는다.

Router의 결과는 BM25·dense 후보 생성 전에 운영정책 revision 허용 집합을 정하고,
Evidence Selector를 통과한 근거가 그 집합 밖으로 벗어나지 않았는지 Generator 진입
직전에 다시 검사하는 데 사용한다.

## 모드 결정

- `current`: 날짜나 과거 의도가 없는 기본 질문. 현재 revision 한 개만 허용한다.
- `historical`: 정확한 기준일이 하나 있는 질문. 그 날짜에 유효했던 revision 한 개만
  허용한다.
- `comparison`: 최신·직전 또는 특정 기준일 revision·직전 revision의 쌍만 허용한다.

기간 값인 `15일 이내` 같은 표현은 과거 날짜로 해석하지 않는다. 과거 의도는 있지만
정확한 날짜가 없거나 연도만 제시된 경우, 두 날짜가 동시에 제시된 경우, 어느 과거본과
현재본을 비교할지 불분명한 경우에는 `needs_clarification=true`로 답변 생성을 막는다.

`최신 정책과 직전 정책`, `변경 전후`처럼 인접 revision 비교가 명시된 질문은 현재
revision 시행일을 기준점으로 삼아 최신·직전 쌍을 선택할 수 있다.

## Generator 진입 가드

Generator 요청에는 다음 정보가 포함돼야 한다.

- `temporal_mode`, `temporal_as_of`
- 허용된 revision과 각 revision의 `valid_from`, `valid_to`, `temporal_role`
- 모드에 맞게 선택된 evidence
- 답변에 표시해야 할 기준일 또는 시행일

현재 모드에서 `superseded` 또는 `default_exposure=false` 근거가 하나라도 들어오거나,
허용 revision 밖의 문서가 들어오면 생성을 차단한다. 비교 모드는
`selected_revision`과 `previous_revision` 근거가 모두 있어야 한다.

이 가드는 Generator에 전달할 요청 계약까지만 만든다. 실제 답변 생성 품질이나 최종
benchmark 승격을 의미하지 않는다.
