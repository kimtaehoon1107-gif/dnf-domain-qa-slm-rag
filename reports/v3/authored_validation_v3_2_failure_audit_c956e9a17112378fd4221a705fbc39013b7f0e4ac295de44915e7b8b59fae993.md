# Authored validation v3.2 failure audit

The set is adaptive validation after this inspection; strict gold is unchanged.

- strict: **16/24**, false-full **6/24**
- provisional adjudicated: **17/24**, false-full **5/24**
- before Q4 six stages: **{"MEASUREMENT": 0, "RETRIEVAL": 1, "ROUTING_SOURCE_SCOPE": 4, "SELECTION_SUPPORT": 1}**
- new stages: **{"MEASUREMENT": 1, "RETRIEVAL": 1, "ROUTING_SOURCE_SCOPE": 5, "SELECTION_SUPPORT": 1}**

| # | stage | response | question | rationale |
|---:|---|---|---|---|
| 1 | MEASUREMENT | full_answer | 은 금고와 세련된 은 금고는 각각 몇 칸이고 가격은 몇 세라야? | FAQ cites the exact same official 40-slot/400-Sera and 56-slot/800-Sera rows as the shop document; strict gold contains only the shop duplicate. |
| 2 | ROUTING_SOURCE_SCOPE | full_answer | 아라드 로얄 패스와 캐릭터 추가 지정권은 각각 몇 세라야? | The route chose shop rather than the event parent containing both prices; headings and purchase guidance were cited without either value. |
| 3 | RETRIEVAL | partial_answer | 2026년 새해맞이 해방의 부스터 던전 버프는 언제 적용됐고 어떤 효과였어? | Monthly-item was correctly routed, but the event body containing the period and both buff values never reached selected evidence; the system honestly returned partial. |
| 4 | ROUTING_SOURCE_SCOPE | full_answer | 캐릭터 컬렉션 등록에 필요한 레벨과 각성 조건은 무엇이야? | The route chose update instead of game guide and cited unrelated level/awakening text as a full answer. |
| 5 | ROUTING_SOURCE_SCOPE | full_answer | 7월 24일 진 각성의 서 아바타 오류는 어떤 직업에 발생했고 어떻게 수정됐어? | The route chose update instead of the dated notice and cited unrelated fixed issues without the affected jobs or client-patch resolution. |
| 6 | ROUTING_SOURCE_SCOPE | partial_answer | 세리아 성장지원 패키지의 가격, 계정당 구매 한도, 청약철회 가능 여부를 알려줘. | The route chose generic FAQ withdrawal guidance instead of the shop product containing price, account limit, and withdrawal eligibility; the system honestly returned partial. |
| 7 | SELECTION_SUPPORT | full_answer | 광휘의 행로 탐사에 필요한 최소 명성과 동시에 진행할 수 있는 탐사 수는 어떻게 돼? | The chosen game-guide chunk contains both exact gold facts, but the assembler cited only the heading and exploration-type text. |
| 8 | ROUTING_SOURCE_SCOPE | full_answer | 퀵계좌이체의 1회·1일·1개월 결제 한도와 하루 횟수 제한을 정리해줘. | The route chose generic FAQ transfer limits instead of the Quick Transfer notice and presented different limits as a full answer. |
