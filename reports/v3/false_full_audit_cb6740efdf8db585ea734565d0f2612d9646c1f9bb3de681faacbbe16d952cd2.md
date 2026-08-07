# False-full nine-case audit

- runtime decision: **DIAGNOSTIC_COMPLETE_RUNTIME_REMAINS_NO_GO**
- A/B/C/D: **2 / 6 / 0 / 1**
- true hardcore wrong-attribute cases: **2**
- catchable/subtle: **6 / 3**

| # | dataset | type | severity | form | one-line comparison |
|---:|---|---|---|---|---|
| 1 | downgraded_canary_32 | B_RETRIEVAL_MISS | catchable | unsupported_requirement_marked_full | 남격투가 밸런스: 11.7%·12.3% 청크가 후보에 없고 패치 제목·시각만 인용됨. |
| 2 | downgraded_canary_32 | D_CROSS_PARENT_MISS | catchable | unsupported_requirement_marked_full | 정책 전후 비교: 서로 다른 revision parent가 필요한데 시행일만으로 비교가 완료된 것처럼 처리됨. |
| 3 | downgraded_canary_32 | A_WRONG_ATTRIBUTE | catchable | unsupported_requirement_marked_full | 전문직업: 배우기 조건 청크가 있었지만 첫 요구에 '전문직업 포기하기' 헤더를 인용함. |
| 4 | downgraded_canary_32 | B_RETRIEVAL_MISS | catchable | wrong_value_presented | 충전 세라: 60개월 FAQ가 후보에 없고 다른 아이템 삭제일·3일 알림을 인용함. |
| 5 | downgraded_canary_32 | B_RETRIEVAL_MISS | subtle | wrong_value_presented | 7월 16일 점검: 04:30~10:00·종료 이벤트 보상 근거가 없고 게시시각·다른 이벤트 보상을 인용함. |
| 6 | downgraded_canary_32 | A_WRONG_ATTRIBUTE | subtle | unsupported_requirement_marked_full | PC방 꿀타임: gold는 후보에 있었지만 일일 참여 단위 대신 주간 19시간·다른 이벤트 계정 단위를 인용함. |
| 7 | downgraded_canary_32 | B_RETRIEVAL_MISS | catchable | unsupported_requirement_marked_full | DirectX 11: 'DirectX 9과 거의 동일' 근거가 후보에 없고 일반적인 DX11 필요 문장만 인용함. |
| 8 | downgraded_canary_32 | B_RETRIEVAL_MISS | catchable | unsupported_requirement_marked_full | 마일리지 시즌7: 50M 한도 근거가 없고 소멸일만 맞는 shop 중복본과 '시즌한정'을 인용함. |
| 9 | adaptive_dev_63 | B_RETRIEVAL_MISS | subtle | unsupported_requirement_marked_full | 비인가 프로그램: 필수 피싱·계정대여 주의 근거가 후보에 없고 관련 운영정책 문장만 인용됨. |

`C_MEASUREMENT_ARTIFACT=0`: no case was removed merely because a nearby or duplicate document stated a similar value; subject and requested attribute still had to be supported.

No question, gold, label, planner output, retrieval result, router, verifier, or assembler was changed.
