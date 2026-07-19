# DNF RAG v3 early generalization canary 계약

## 목적과 지위

이 canary는 기존 63개 adaptive dev에 새 규칙을 맞추기 전에 처음 보는 질문에서
canonical claim-aware reranker의 성능이 유지되는지 확인한다. 기존 frozen blind와
분리하며 이를 열거나 검색하거나 평가하지 않는다.

본 계약은 질문과 gold를 만들기 전에 표본 구성, 지표와 gate를 고정한다. 현재
agent가 slot과 계약을 작성했으므로 독립 holdout이 아니다. 질문과 gold까지 같은
주체가 작성하면 반드시 `authored_canary`로 부르고, 사용자 또는 별도 독립 검수
주체가 질문·근거·시간 상태를 확인해야 실행할 수 있다.

## 표본 설계

- 총 32개 slot
- 공지, 업데이트, 이벤트, 게임가이드, FAQ, 운영정책, 세리아 상점,
  이달의 아이템 각 4개
- single 8, multi 8, partial 5, false 3, historical 4, preview 1,
  realtime 2, comparison 1
- multi 질문에는 `각각`, `비교`, `함께`를 사용하지 않는다.
- 기존 63개 질문의 단순 paraphrase를 금지한다.
- answerable slot은 가능한 한 기존 dev와 다른 parent document를 사용한다.
- 질문 작성자는 retrieval 결과를 보지 않으며 gold 검수자는 질문 작성과 분리한다.

질문·gold가 아직 없는 slot 계획만 먼저 content-addressed artifact로 동결한다.

## 실행 전 무결성

- normalized exact question overlap: 0
- 기존 dev와 question token Jaccard 0.50 이상: 0
- 제목에서 직접 만든 질문: 0
- 가능한 answerable slot의 dev parent overlap: 0
- 질문 작성 완료 후 gold·time scope·source를 별도 사람이 검수
- 전체 질문/gold artifact를 freeze한 뒤에만 첫 실행

질문 작성 전 corpus feasibility 감사에서 현재 운영정책은 단일 current revision 부모만,
현재 이달의 아이템은 단일 부모·단일 청크만 존재함을 확인했다. 따라서 운영정책의
current/mixed 3개 slot은 dev parent 중복만 허용하고 chunk·atomic claim 분리를
요구한다. 이달의 아이템 current 2개 slot은 dev parent·chunk 중복을 허용한다.
single slot은 dev에 없던 획득 방법 claim을 사용하고, multi slot은 현재 단일 청크의
모든 주요 fact가 이미 dev에 쓰였으므로 새 질문 조합만 검증하는 제한적 canary로
표시한다. 이 5개 예외는 질문·gold 작성 및 점수 확인 전에 등록하며, 나머지
answerable slot은 dev parent·chunk 중복을 모두 0으로 유지한다. 지표와 GO/NO-GO
threshold는 변경하지 않는다.

## 사전 고정 지표와 gate

표본 수가 32개뿐이므로 비율과 함께 분자/분모 및 Wilson 95% confidence interval을
반드시 보고한다. source별 분모가 작다는 한계를 명시한다.

| 지표 | GO gate |
|---|---:|
| retrieval all-required evidence recall | 0.90 이상 |
| selected evidence-group hit | 0.85 이상 |
| cited evidence-group hit | 0.85 이상 |
| claim completeness | 0.90 이상 |
| canonical unified baseline 대비 strict regression | 0건 |
| promotion 후보의 strict improvement | 1건 이상 |
| source별 최저 retrieval all-required recall | 0.66 이상, 0-hit source 없음 |
| temporal/revision violation | 0건 |
| false/realtime evidence exposure | 0건 |
| partial disclaimer | 5/5 |

한 hard gate라도 실패하면 canary 결과는 `NO-GO`다. canary 실패 사례를 열어 규칙을
수정하면 그 세트는 즉시 `adaptive_validation`으로 강등하며 sealed benchmark나
독립 holdout으로 재사용하지 않는다.

## 이후 순서

canary 통과 전에는 temporal 규칙, NLI, 자연어 Generator를 더 쌓지 않는다.
통과 후 source별 validity 계약을 확정한다. 장기 보안 공지는 `last_verified_at`
하나로 current 처리하지 않고 `validity_state`, `validity_reason`,
`validity_evidence`, `verified_by`, `reverify_after`를 요구한다.

운영정책 contradiction은 50개 과거 revision 전체가 아니라 동일 조항의 temporal
diff에서 동시에 참일 수 없는 atomic claim만 대상으로 한다. 자연 3-class NLI가
gate를 통과하지 못하면 자연어 Generator는 `NO-GO`로 유지하고 exact extractive
Generator만 허용한다.

최종 평가는 v2↔v3 공통 연속성 세트와 v3 sealed benchmark를 분리한다. 구조화
store, Neople API, 앱 통합은 Cycle 5 이후 선택적 productization으로 둔다.
