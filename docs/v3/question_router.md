# DNF RAG v3 Question Router 계약

## 목적과 범위

Question Router는 질문을 공식 코퍼스의 출처와 시간 경로로 분기한다. 이 단계에서는
질문 분해를 실행하거나 자유형 답변을 생성하지 않는다.

지원하는 기본 intent는 다음과 같다.

- `guide_rule`: 게임가이드
- `patch_change`: 라이브 업데이트 또는 명시적 퍼스트 서버 preview
- `active_event`: 이벤트
- `known_issue` / `official_notice`: 오류·핫픽스·보안·일반 공지
- `account_policy`: 최신 또는 명시 시점의 운영정책
- `faq_support`: FAQ
- `shop_price`: 세리아 상점과 이달의 아이템
- `multi_document`: 둘 이상의 근거 경로 또는 비교·각각 질문
- `realtime_api`: 경매장 실시간 시세, 사용자 계정 상태
- `unanswerable` / `ood_safety`: 코퍼스 밖 요청 또는 안전상 거절

## 판단 순서

1. 코퍼스로 답할 수 없는 요청과 향후 실시간 API 요청을 먼저 차단·분리한다.
2. `운영정책`, `이달의 아이템`, `퍼스트 서버`처럼 명시적인 출처 신호를 적용한다.
3. 공개 문서 제목과 질문의 고유 토큰 겹침을 확인한다.
4. 출처 신호가 없으면 기존 hybrid top-20의 출처 순서를 보조 신호로 사용한다.
5. 결정된 `source_id`, `source_kind`, 시간 정책으로 BM25·dense 후보를 검색 전에 제한한다.

규칙이나 제목에 정답 document ID, gold chunk ID를 사용하지 않는다. 개발 평가는 기존
adaptive retrieval dev만 사용하며 final blind로 부르지 않는다.

## 시간·노출 정책

- `current`: `default_exposure=true`, `current/upcoming`만 허용한다.
- `historical`: 명시적인 과거 질문에서만 비기본 `expired/superseded` 자료를 허용한다.
- `preview`: 퍼스트 서버가 명시된 질문에서만 `preview_patch`를 허용한다.
- `mixed`: 현재·과거 항목을 함께 묻는 질문이며 decomposition 대기 상태로 넘긴다.
- 운영정책은 별도 Temporal Router의 `current/historical/comparison` revision 선택을
  그대로 사용한다.

가이드와 FAQ는 현재 코퍼스에 완전한 과거 revision 계보가 없으므로, 과거 시점 질문을
현재 문서로 추측해 답하지 않고 clarification으로 막는다.

종료 이벤트·상품, 과거 정책, preview는 명시적 시간 경로 없이 기본 검색에 들어가지
않는다. 경매장 시세와 사용자 캐릭터·계정 상태는 corpus snapshot이 아니라
`realtime_api` 경로로 분리한다.

## 다중 문서

`각각`, `함께`, `비교`처럼 여러 근거가 필요한 질문 또는 서로 다른 두 출처가 선택된
질문은 `needs_decomposition=true`, `route_action=decompose`로 반환한다. 이번 사이클은
하위 질문 생성이나 결과 병합을 실행하지 않는다.

## 승격 의미

Router GO는 adaptive dev에서 출처·시간 분기와 검색 전 필터가 기준을 통과했다는 뜻이다.
질문 분해, Generator, Verifier, 최종 benchmark의 GO를 의미하지 않는다.
