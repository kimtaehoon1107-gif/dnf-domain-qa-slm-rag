# DNF 공식 문서 QA/RAG v3 재설계 인계서

## 1. 프로젝트 목표

던전앤파이터 공식 문서를 근거로 사용자 질문에 답하고, 답변마다 정확한 출처를 제시하는 평가 주도형 QA/RAG 시스템을 새로 설계한다.

기존 v2를 삭제하거나 덮어쓰지 않는다. v2는 비교 기준선과 실패 기록으로 보존하고, v3에서 코퍼스·검색·근거 선택 구조를 사실상 처음부터 다시 설계한다.

최종 목표 구조는 다음과 같다.

```text
Question
→ Question Router
→ 필요할 때만 Question Decomposition
→ 유형별 Sub-question Retrieval
→ Evidence Selector
→ Generator
→ Verifier
→ 근거가 검증된 최종 답변
```

단순히 최신 구조를 구현하는 것이 아니라, 각 단계가 실제 평가에서 개선됐을 때만 승격한다.

## 2. 핵심 원칙

### 기존 프로젝트 보존

- 기존 v2 결과와 canonical 설정을 변경하지 않는다.
- v3는 별도 브랜치·데이터·인덱스·보고서 경로에서 진행한다.
- 기존 실패 분석과 평가 코드는 최대한 재사용한다.
- 기존 파일을 정리하거나 삭제하지 않는다.

### 평가 우선

- 좋은 숫자를 만들기보다 정직하게 실패 원인을 측정한다.
- 한 번에 여러 요소를 바꾸지 않는다.
- 단계별 A/B 실험으로 원인을 분리한다.
- retrieval과 generation을 따로 평가한다.
- answerability 단독으로 성능을 판단하지 않는다.

### Blind 보호

- 기존 frozen blind test는 개발 중 절대 검색하거나 생성하지 않는다.
- blind 문서는 학습 QA뿐 아니라 RAFT의 모든 distractor에서도 제외한다.
- v3 최종 설계가 완전히 고정된 뒤에만 blind 실행을 검토한다.
- 기존 blind를 개발에 사용한다면 별도의 신규 blind v2가 필요하다.

### 모델 학습은 마지막

검색되지 않은 근거는 Generator나 LoRA가 복구할 수 없다.

따라서 코퍼스와 검색 문제를 해결하기 전에는 새로운 RAFT/LoRA 학습을 시작하지 않는다.

## 3. 기존 v2에서 유지할 자산

다음은 새로 만들지 말고 재사용하거나 확장한다.

- 공식 문서 수집 로직과 원본 데이터
- `parent_doc_id` 기반 원문-청크 관계
- `source_url`, 날짜 및 출처 메타데이터
- BGE-M3 retrieval 기준선
- parent/chunk/question 누수 검사
- evidence span 존재 여부 검사
- gold evidence visibility 검사
- RAFT gold 위치 균형 검사
- answer-aware hard-negative 필터
- blind freeze 및 해시 기록 정책
- exact citation, partial joint, false joint, safety 평가
- 기존 최종 결과와 실패 분석 문서

BGE-M3는 현재 canonical 기준선으로 계속 유지한다. 새로운 embedding 모델은 별도 A/B 후보일 뿐 즉시 교체하지 않는다.

## 4. 확인된 현재 문제

현재 코퍼스 집계:

- 부모 문서 188개
- 청크 1,307개
- 게임 가이드 부모 125개, 청크 1,110개
- 패치노트 부모 20개
- 이벤트 부모 23개
- 공지 부모 13개
- 청크 길이 중앙값 약 262자
- 200자 미만 청크 504개
- 100자 미만 청크 192개
- 동일 텍스트 청크 11개 그룹, 총 31개
- 가이드 125개 중 111개는 카테고리 누락
- 가이드 44개는 갱신일 누락
- 유효기간이 기록된 부모 문서는 22개

검색의 주요 문제:

- 도메인 평가 90개 중 58개에서 정답 근거가 top-3에 없음.
- 현재 `hybrid`는 진짜 BM25+dense hybrid가 아님.
- 먼저 dense top-100을 가져온 뒤 그 내부에서 token overlap으로 재정렬함.
- dense 후보에 들어오지 않은 문서는 lexical 검색으로 복구할 수 없음.
- lexical 점수도 정식 BM25가 아니라 제목·본문 토큰 겹침 점수임.
- 전역 reranker, parent window, deterministic contextual prefix는 기존 실험에서 승격에 실패함.
- 실패한 실험을 같은 방식으로 반복하지 않는다.

## 5. 권장 우선순위

```text
1. v2 기준선 동결
2. 코퍼스 인벤토리와 품질 감사
3. v3 문서·청크 스키마 설계
4. 코퍼스 v3 정제
5. 진짜 BM25 + Dense Hybrid
6. Question Router
7. route별 Evidence Selector
8. 복합 질문에만 Question Decomposition
9. Generator와 Verifier
10. 마지막에 RAFT/LoRA
```

Question Router나 agentic 구조부터 구현하지 않는다. 먼저 검색 가능한 지식이 정확하게 구성돼 있어야 한다.

## 6. v3 코퍼스 목표 구조

### 원본 문서

최소 필드:

```text
document_id
source_snapshot_id
canonical_url
source_kind
authority
title
category_path
published_at
valid_from
valid_to
revision_id
supersedes_document_id
status
content_hash
fetched_at
parser_version
raw_source_path
```

`status` 예시:

```text
current
expired
upcoming
superseded
unknown
```

원본은 immutable snapshot으로 보존한다. 사이트 내용이 변경됐을 때 기존 원본을 덮어쓰지 않고 새 revision을 만든다.

### 청크

최소 필드:

```text
chunk_id
parent_document_id
heading_path
chunk_type
display_text
retrieval_text
start_offset
end_offset
token_count
entities
valid_from
valid_to
chunker_version
```

중요 원칙:

- `display_text`: 사용자에게 보여주고 인용할 실제 원문
- `retrieval_text`: 제목·섹션·엔티티를 보강한 검색 전용 텍스트
- 두 필드를 혼합하지 않는다.
- 모든 청크는 원문 위치로 역추적할 수 있어야 한다.

### 문서 유형별 저장소

하나의 평면 인덱스만 사용하지 않는다.

```text
game_guide_index
patch_note_index
event_store
known_issue_index
account_policy_index
shop_price_store
```

이벤트는 다음을 구조화한다.

```text
event_name
start_at
end_at
eligibility
reward
claim_method
status
source_document_id
evidence_chunk_id
```

패치노트는 가능하면 다음 단위로 구조화한다.

```text
patch_date
target_entity
change_type
before_value
after_value
description
source_document_id
evidence_chunk_id
```

## 7. 코퍼스 감사 항목

처음 구현할 것은 대규모 재청킹이 아니라 코퍼스 감사 도구다.

필수 검사:

- 공식 사이트에서 발견 가능한 문서 수 대비 수집률
- URL·문서·청크 중복
- 빈 제목·카테고리·날짜
- 지나치게 짧은 고립 청크
- 원문과 청크의 offset 역추적
- 표의 행과 열 손실
- 이미지에만 존재하는 핵심 정보
- 같은 사실의 최신·과거 문서 충돌
- 수정·삭제·신규 문서 탐지
- content hash 변화
- parser/chunker/index 버전 기록
- 만료 이벤트가 현재 검색 결과에 노출되는지 여부

코퍼스 v3는 기존 canonical 파일을 덮어쓰지 않고 새로운 artifact로 생성한다.

## 8. 청킹 전략

문서 유형에 따라 다르게 처리한다.

### 게임 가이드

- 제목과 heading path 보존
- 섹션·문단·표 경계를 우선
- 의미가 없는 초단문 청크는 형제 청크와 병합
- `연관 가이드`, 표 제목만 있는 청크 등은 별도 처리
- 작은 청크로 검색하고 부모 문단을 생성 문맥으로 제공하는 small-to-big 후보를 평가

### 공지·운영 정책

- 평평한 문서는 기존 fixed chunking을 기준선으로 유지
- 문장 경계를 보존하는 fixed-window v2를 별도 평가
- 기존 section chunking 실패를 무시하고 재승격하지 않는다.

### 이벤트

- 자연어 청크와 구조화 fact row를 함께 생성
- 현재 시점 필터를 필수로 적용

### 패치노트

- 날짜, 대상 콘텐츠, 변경 항목 단위로 분리
- 과거와 현재 사실이 섞이지 않도록 revision 관계를 보존

## 9. 진짜 Hybrid Retrieval

목표 구조:

```text
Dense top-N ─┐
             ├→ 합집합 및 중복 제거 → 필터 → Evidence Selector
BM25 top-N ──┘
```

필수 조건:

- BM25와 dense가 독립적으로 후보를 생성
- 한쪽 검색 결과가 다른 쪽 후보군에 제한되지 않음
- parent 중복 완화
- 문서 유형과 시간 필터 지원
- candidate recall과 final top-k를 분리 측정

초기 비교군:

```text
BGE-M3 dense
BM25
BGE-M3 + BM25
Qwen3-Embedding 후보
Qwen3 + BM25
```

Qwen3는 A/B 후보이며, 프로젝트 dev 평가에서 이길 때만 검토한다.

## 10. Question Router

초기 intent:

```text
guide_rule
patch_change
active_event
known_issue
account_policy
shop_price
multi_document
unanswerable
ood_safety
```

출력 예시:

```json
{
  "intent": "active_event",
  "required_sources": ["event_store"],
  "time_scope": "current",
  "needs_decomposition": false
}
```

처음에는 규칙과 작은 분류기로 기준선을 만든다. LLM router는 필요성이 확인된 뒤 A/B 평가한다.

## 11. Question Decomposition

모든 질문에 적용하지 않는다.

적용 대상:

- A와 B 비교
- 여러 콘텐츠 조건을 동시에 질문
- 패치 전후 차이
- 기간·보상·참여 조건을 함께 질문
- 서로 다른 문서의 근거가 필요한 질문

처리 과정:

```text
원 질문
→ 독립적으로 답할 수 있는 하위 질문 생성
→ 하위 질문별 검색
→ 후보 합집합
→ 중복·충돌 정리
→ Evidence Selector
```

단일 사실 질문은 기존 1회 검색 경로를 유지한다.

## 12. Evidence Selector와 Verifier

Evidence Selector는 후보 recall이 확보된 뒤 개발한다.

route별 우선순위:

- 가이드: 질문-근거 직접성
- 이벤트: 시간 유효성
- 패치: 날짜와 대상 일치
- partial: 지원되는 요구사항별 evidence slot
- false: 관련 문서가 있어도 답 자체가 존재하는지 판정

Verifier 검사:

- 답변 claim마다 지지 근거가 있는가
- 인용 청크가 실제 claim을 지지하는가
- 요구사항이 누락되지 않았는가
- 만료 정보를 현재 사실처럼 말하지 않았는가
- 근거끼리 충돌하지 않는가
- true/partial/false 판정이 근거와 일치하는가

## 13. 평가 지표

### 코퍼스

```text
source coverage
freshness
metadata completeness
duplicate rate
short/orphan chunk rate
parse accuracy
version conflict rate
```

### Retrieval

```text
BM25 candidate recall
dense candidate recall
union candidate recall
parent hit_rate@k
chunk hit_rate@k
MRR
all-required-evidence recall
temporal correctness
```

### Evidence Selector

```text
evidence precision
evidence recall
evidence sufficiency
contradiction rate
noise rate
```

### Generation

```text
exact citation
claim precision/recall
faithfulness
partial joint
false joint
unsupported abstention
safety
schema compliance
latency
```

기존 `parsed_citation_hit`는 any-hit라 관대하므로, 복합 질문에서는 모든 필수 evidence slot이 인용됐는지도 별도로 측정한다.

## 14. 승격 게이트

다음 질문에 순서대로 답해야 한다.

1. 정답 문서가 코퍼스에 존재하는가?
2. 정답 문서가 candidate pool에 들어오는가?
3. 후보에는 있지만 selector가 놓치는가?
4. selector가 골랐지만 generator가 활용하지 못하는가?
5. 생성했지만 verifier가 오류를 잡지 못하는가?

RAFT/LoRA는 4번이 주요 병목으로 확인될 때만 진행한다.

승격 조건:

- 공통 dev 세트에서 기준선보다 개선
- 다른 질문 유형에서 큰 회귀 없음
- blind 미사용
- 누수 검사 통과
- latency와 비용 보고
- 같은 평가 지표로 비교
- 단일 지표가 아니라 retrieval·citation·partial·false·safety를 공동 판단

## 15. 금지 사항

- 기존 v2 canonical 결과 덮어쓰기
- 기존 frozen blind를 개발 중 실행
- 기존 blind 문서를 RAFT distractor에 포함
- 현재 `hybrid`를 진짜 BM25 hybrid라고 보고
- 실패한 contextual prefix나 parent-window를 그대로 재실험
- candidate recall을 확인하지 않고 reranker부터 추가
- 검색 실패를 Generator 프롬프트로 해결하려 시도
- 코퍼스와 검색이 안정되기 전에 새 LoRA 학습
- answerability accuracy만 보고 승격
- 여러 기능을 한 arm에서 동시에 변경
- 최신 논문이라는 이유만으로 GraphRAG나 agentic loop를 전면 도입

## 16. 첫 번째 실행 목표

첫 사이클에서는 코드를 대규모로 변경하지 말고 다음까지만 진행한다.

```text
1. 기존 v2 상태와 canonical artifact 확인
2. v3 작업 경로와 artifact 명명 규칙 제안
3. 코퍼스 감사 스크립트 설계
4. 현재 원본·부모·청크 통계 산출
5. 누락·중복·초단문·날짜·카테고리 문제 목록 생성
6. document/chunk schema v3 제안
7. 변경 전 사용자 승인 또는 명시적 실행 지시 대기
```

성공 기준은 “새 모델이 실행됨”이 아니라 다음이다.

> 현재 코퍼스의 수집 범위와 품질 문제가 재현 가능한 보고서로 측정되고, v3 스키마 및 첫 A/B 실험의 변경 범위가 명확해진 상태.
