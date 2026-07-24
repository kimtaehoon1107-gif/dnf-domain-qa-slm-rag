# Typed evidence-ref 일반화 평가 프로토콜

## 현재 상태

이 평가는 아직 실행할 수 없다. 질문과 정답이 작성되지 않았고 사람 검수도
끝나지 않았기 때문이다.

```text
현재 상태: questions_unwritten_execution_locked
목표: 64문항
최소 승인 수: 60문항
```

질문 작성과 사람 검수가 끝나고 전체 파일의 SHA-256을 동결하기 전에는 검색,
reranker, Qwen 생성, verifier, 자동 채점을 실행하지 않는다.

## 평가 대상 기준선

동결 대상은 다음 구성이다.

```text
Subject-anchored 검색
→ 질문당 요구 전체를 한 번에 생성
→ 비표: typed value + evidence_ref
→ 표: table-row branch
→ relation / temporal-role / boolean verifier
→ Qwen3 8B ctx8192
```

adaptive 32문항의 5번과 14번을 위한 추가 규칙은 이 일반화 평가가 최초로
끝날 때까지 넣지 않는다.

## 표본 구성

64개 슬롯은 공식 출처 8종과 주된 난이도 8종을 한 번씩 교차한다.

출처:

- 공지
- 업데이트
- 이벤트
- 게임가이드
- FAQ
- 운영정책
- 세리아 상점
- 이달의 아이템

주된 난이도:

- 게시일·적용일·판매일·삭제일 같은 temporal role
- boolean 긍정·부정
- 유사한 형제 조항 또는 형제 속성
- 2~3개 요구
- 표의 가격·거래 타입·삭제 시각·구성품
- 현재 revision과 과거 revision
- 근거 없음 또는 일부만 근거 있음
- 단일 직접 사실

출처 특성상 특정 조합이 성립하지 않으면 다른 문서로 바꿀 수는 있지만, 슬롯의
출처와 주된 난이도는 평가를 실행하기 전에 유지하거나 변경 사유를 기록해야 한다.

## 작성 스키마

각 요구는 하나의 gold 문자열이 아니라 다음을 가진다.

```json
{
  "requirement_id": "requirement_1",
  "subject": "대상",
  "relation": "질문한 관계",
  "value_type": "datetime",
  "required_values": ["2026-08-13T06:00"],
  "acceptable_evidence_units": [
    {
      "document_id": "document_...",
      "chunk_id": "chunk_...",
      "start_char": 120,
      "end_char": 142,
      "text": "원문과 정확히 일치하는 근거"
    }
  ]
}
```

공식 문서에 같은 사실을 직접 말하는 문장이 둘 이상 있으면 모두
`acceptable_evidence_units`에 넣는다. 내용은 맞지만 관계를 직접 증명하지 않는
문장은 넣지 않는다.

## 사람 검수

각 문항은 다음을 확인한다.

1. 질문이 제목을 그대로 바꾼 문장이 아니라 실제 본문 사실을 묻는다.
2. `subject`, `relation`, `required_values`가 질문과 일치한다.
3. 모든 허용 근거가 원문 좌표와 정확히 일치한다.
4. temporal role과 revision이 질문 시점에 맞는다.
5. 형제 조항이나 형제 표 행이 정답으로 잘못 허용되지 않았다.
6. 근거 없음·부분답 문항은 실제로 전체 근거가 없거나 일부만 있다.
7. 기존 adaptive 32 및 이전 canary 질문의 단순 재표현이 아니다.

검수 결과는 `approved`, `rewrite`, `rejected` 중 하나다. `approved` 외 문항은
freeze 대상에 들어갈 수 없다.

## Freeze gate

다음을 모두 만족해야 최초 실행이 가능하다.

```text
승인 문항: 60개 이상
필수 필드 누락: 0
원문 좌표 불일치: 0
정규화 질문 중복: 0
adaptive 32 exact 질문 중복: 0
이전 canary exact 질문 중복: 0
미등록 parent 중복 예외: 0
pending 검수: 0
평가 파일 SHA-256 기록: 완료
```

운영정책이나 이달의 아이템처럼 현재 공식 parent가 하나뿐인 출처는 parent 중복이
불가피할 수 있다. 이 경우 질문과 atomic claim이 새로워야 하며, 실행 전에 예외
사유를 문항에 적는다.

## 최초 A/B

freeze 뒤 첫 실행에서만 같은 입력으로 다음 두 Arm을 비교한다.

```text
Arm A: 이전 batched split-schema
Arm B: typed value + evidence_ref
```

함께 기록할 지표:

- 후보 보유율
- 내용상 완전 정답이면서 직접 근거가 있는 비율
- 부분답
- 실제 false-full
- verifier overreject
- 인용 좌표 복원 성공률
- 생성 오류
- 문항별 호출 수
- 입력·출력·전체 토큰
- 평균, p50, p95 응답시간

GO gate:

```text
실제 false-full = 0
의미 기준 완전 정답 >= 85%
Arm A 대비 의미 정답 회귀 = 0
인용 좌표 복원 = 100%
생성 오류 = 0
```

64문항에서 false-full이 0건이면 이항 오류율의 단순 rule-of-three 95% 상한은
약 4.7%다. 따라서 0건이라는 사실만으로 실제 오류율이 0이라고 주장하지 않는다.

## 실패 처리

실패를 보기 전에 다음 세 구간으로만 분류한다.

```text
A. 후보에 정답 없음
B. 후보는 있으나 모델이 값 또는 evidence unit을 잘못 선택
C. 모델 값은 맞으나 verifier가 차단
```

동일 패턴이 여러 문항에서 반복될 때만 일반 규칙 후보로 기록한다. 실패 문항을
열어 규칙을 바꾸는 순간 이 세트는 `adaptive_validation`으로 강등하며 같은 세트로
다시 일반화 성능을 주장하지 않는다.

## 라이브와 속도

GO 뒤에도 기존 경로를 제거하지 않는다. 새 경로는
`typed_evidence_ref_enabled` 플래그로 shadow 또는 제한 데모에 먼저 연결한다.
정확성 승격을 결정한 뒤에만 입력 압축과 표 질문 LLM 우회를 별도 A/B로 진행한다.

