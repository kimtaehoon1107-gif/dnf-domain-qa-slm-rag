# Labeling Guide

이 가이드는 DNF Domain QA SLM/RAG v2의 질문 intent, answerability, evidence quality를 일관되게 라벨링하기 위한 기준입니다.

Label Studio 작업에는 [labeling/label_studio_config.xml](../labeling/label_studio_config.xml)을 사용하고, export 결과는 [labeling/export_schema.json](../labeling/export_schema.json) 형식으로 정규화합니다.

## 1. Labeling Principles

- 문서에 있는 내용만 기준으로 판단합니다.
- 실제 게임 지식이나 기억으로 빈칸을 채우지 않습니다.
- 날짜, 기간, 보상, 수치, 아이템명은 원문 근거가 없으면 확정하지 않습니다.
- 질문이 여러 의도를 포함하면 사용자의 핵심 요구를 기준으로 1개 intent를 선택합니다.
- 답변 가능성이 애매하면 `partial`을 우선 고려하고, 어떤 부분이 부족한지 notes에 적습니다.

## 2. Intent Labels

### patch_note

패치노트, 업데이트 변경점, 밸런스 조정, 시스템 개편 질문입니다.

예:

- "7월 패치에서 소환사는 뭐가 바뀌었어?"
- "장비 성장 시스템 변경점 알려줘"

### notice

점검, 서비스 공지, 접속 제한, 사전 안내 질문입니다.

예:

- "정기점검 시간이 언제야?"
- "임시점검 보상 있어?"

### event

이벤트 기간, 참여 조건, 보상, 교환 상점 질문입니다.

예:

- "썸머 코인 이벤트 보상 뭐야?"
- "이벤트 상점은 언제까지 이용 가능해?"

### game_system

성장, 장비, 던전, 재화, UI, 편의성 같은 시스템 질문입니다.

예:

- "명성 보정은 어떻게 적용돼?"
- "장비 성장 재료가 부족하면 어떻게 돼?"

### character_item

캐릭터, 전직, 스킬, 아이템 옵션, 세트 효과 질문입니다.

예:

- "남레인저 신규 탈리스만 효과 알려줘"
- "새 에픽 장비 옵션이 뭐야?"

### operation_policy

제재, 복구, 비인가 프로그램, 운영정책 질문입니다.

예:

- "비인가 프로그램 사용하면 어떻게 돼?"
- "아이템을 실수로 버렸는데 복구 가능해?"

### account_payment

계정 보안, 본인 인증, 결제, 환불, 캐시 관련 질문입니다.

예:

- "결제 취소는 어떻게 해?"
- "OTP 해제하려면 뭐가 필요해?"

### bug_known_issue

알려진 오류, 수정 예정, 임시 조치, 버그 영향 범위 질문입니다.

예:

- "레이드 보상 표시 오류가 있어?"
- "특정 스킬이 안 맞는 문제 수정됐어?"

### recommendation

추천, 비교, 선택 질문입니다. 문서 근거가 있어도 개인 상태에 따라 답이 달라질 수 있습니다.

예:

- "복귀 유저는 어떤 캐릭터가 좋아?"
- "이벤트 보상 뭐부터 받아야 해?"

### unknown

문서 범위 밖이거나 질문 의도가 불명확한 경우입니다.

예:

- "내 계정 왜 그래?"
- "오늘 메타 정답 알려줘"

## 3. Answerability Labels

### true

검색된 문서가 질문에 직접 답합니다.

기준:

- 핵심 사실이 문서에 명시되어 있음
- 날짜/기간/보상/수치가 문서에 있음
- 답변에 필요한 조건이 충분함

### partial

문서가 일부만 답하거나 조건부 답변만 가능합니다.

기준:

- 관련 문서는 있으나 사용자의 구체 조건이 부족함
- 일부 세부 수치나 기간이 없음
- 추천 질문처럼 개인 상태에 따라 달라짐

### false

문서만으로 답할 수 없습니다.

기준:

- 관련 문서가 없음
- 문서가 질문의 핵심을 다루지 않음
- 계정별 상태, 실시간 장애, 현재 거래 가격처럼 외부 확인이 필요함

## 4. Evidence Quality

### good

- 문서가 질문의 핵심 답을 직접 포함함
- evidence 문서 1개만으로도 답변 가능함

### partial

- 관련 문서는 있으나 답변 일부만 지원함
- 여러 문서를 조합해야 하며 일부 조건은 불명확함

### poor

- 검색된 문서가 주제만 비슷하고 직접 근거가 아님
- 답변하면 hallucination 위험이 높음

## 5. Expected Answer Writing Rules

- 짧고 검증 가능한 문장으로 작성합니다.
- 근거 문서에 없는 수치나 이름을 추가하지 않습니다.
- `answerability=false`는 "수집된 문서만으로는 확인할 수 없습니다." 형태로 작성합니다.
- `partial`은 "확인 가능한 부분은 ..."과 "추가 확인이 필요한 부분은 ..."을 분리합니다.

## 6. Failure Categories

- `retrieval_failure`: 정답 문서가 검색되지 않음
- `outdated_document_usage`: 더 최신 문서 대신 과거 문서를 사용함
- `unsupported_hallucination`: 문서에 없는 내용을 생성함
- `date_or_period_error`: 날짜, 점검 시간, 이벤트 기간을 틀림
- `item_name_or_numeric_value_error`: 아이템명, 보상명, 수치를 틀림
- `forced_answer_to_unanswerable_question`: 근거가 없는데 답변을 강행함

## 7. Labeling QA Checklist

- 질문 intent가 하나로 정리되는가?
- evidence 문서가 실제로 expected answer를 뒷받침하는가?
- answerability와 evidence_quality가 서로 모순되지 않는가?
- 날짜/기간/보상/수치가 expected answer에 있다면 문서에도 있는가?
- unanswerable 질문이 강제로 답변되지 않았는가?
