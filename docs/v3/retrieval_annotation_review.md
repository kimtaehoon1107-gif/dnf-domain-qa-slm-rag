# DNF RAG v3 검색 평가 문항 검토

## 검토 대상

질문 `비인가 프로그램 사용 주의사항은 뭐야?`의 고정 gold는 계정 대여 후 사기·비인가 프로그램 사용에 악용되면 정상 참작이 불가하다는 공지를 가리킨다. 그러나 현재 운영정책, FAQ, 최근 제재 공지도 일반적인 질문 표현에 대한 공식 근거가 될 수 있다.

에이전트 증거 감사는 이 문항을 `underspecified_question_multiple_valid_official_answers`로 분류했다. 이는 사람 판정을 대신하지 않는다.

## 권고

사람 검토 후 질문을 다음처럼 범위를 좁혀 다시 freeze하는 방안을 권고한다.

> 계정을 타인에게 빌려줬다가 사기나 비인가 프로그램 사용에 이용되면 정상 참작을 받을 수 있어?

현재 상태는 다음과 같다.

- human review: PENDING
- 기존 dev set 수정: 없음
- 학습 사용: 금지
- 최종 benchmark 사용: 금지
- dev refreeze: NO-GO

## 고정 산출물

- review packet: `data/v3/evaluation/retrieval_annotation_review_packet_6224137078afbea7067c10f40b31009adb74fd5fda30cdd5334fcbe74b1e3037.jsonl`
- manifest: `data/v3/evaluation/retrieval_annotation_review_manifest_a73c22708fa24fd4311cde62675d59137358d185cdca1eb223d284d2e7e0d258.json`
- report: `reports/v3/retrieval_annotation_audit_701be217544ab3686a3fae279d6c2885fe93483f391078829da1d8e98cdbd12c.json`
