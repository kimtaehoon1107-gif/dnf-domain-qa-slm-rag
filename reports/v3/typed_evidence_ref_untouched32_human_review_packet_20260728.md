# Typed evidence-ref 신규 32문항 사람 검수 패킷

> 상태: 초안 / 실행 잠금. 각 문항의 질문, 요구별 정답, 공식 원문을 검수한 뒤 승인 여부를 기록합니다.

## 01. 7월 8일 퍼스트 서버는 원래 몇 시 오픈 예정이었고, 실제로 몇 시로 지연됐어?

- 출처: `dnf_notice`
- 유형: `temporal_role`
- 기대 응답: `full_answer`
- 공식 문서: [7/8(수) 퍼스트 서버 오픈 지연 안내 (15시→15시 10분)](https://df.nexon.com/community/news/notice/2927926)

### scheduled_open_at

- subject: `7월 8일 퍼스트 서버`
- relation: `scheduled_open_at`
- value type: `time`
- 정답: `["15:00"]`

공식 원문:

```text
▣ 퍼스트 서버 오픈 지연 - 15:00 → 15:10
```

좌표: `chunk_sha256_9da595117eabcbb8dd807ce968a09659fd37b876281e0473cad040fab71b505d:127:157`

### delayed_open_at

- subject: `7월 8일 퍼스트 서버`
- relation: `delayed_open_at`
- value type: `time`
- 정답: `["15:10"]`

공식 원문:

```text
▣ 퍼스트 서버 오픈 지연 - 15:00 → 15:10
```

좌표: `chunk_sha256_9da595117eabcbb8dd807ce968a09659fd37b876281e0473cad040fab71b505d:127:157`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:
## 02. 2026년 7월 2일 공지 시점에 DirectX 9 지원은 이미 종료된 상태였어?

- 출처: `dnf_notice`
- 유형: `boolean_direction`
- 기대 응답: `full_answer`
- 공식 문서: [DirectX 11 지원 관련 추가 안내](https://df.nexon.com/community/news/notice/2927887)

### support_already_ended

- subject: `DirectX 9 지원`
- relation: `support_already_ended`
- value type: `boolean`
- 정답: `[false]`

공식 원문:

```text
이러한 안정화 추이를 바탕으로 향후 DirectX 9 지원 종료를 검토하고 있음을 안내드리며,
```

좌표: `chunk_sha256_cc084dfce98e4929261538f9112d58ce05f7c427b9eac8c066c5167bda02817d:345:397`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 03. Npay 7% 적립 이벤트의 최소 충전금액, 적립률, 최대 적립액은 각각 얼마였어?

- 출처: `dnf_notice`
- 유형: `multi_requirement`
- 기대 응답: `full_answer`
- 공식 문서: [Npay 7% 네이버페이 포인트 적립 이벤트](https://df.nexon.com/community/news/notice/2927921)

### minimum_charge

- subject: `Npay 7% 적립 이벤트`
- relation: `minimum_charge`
- value type: `currency`
- 정답: `[{"amount": 40000, "unit": "원"}]`

공식 원문:

```text
■ 이벤트 내용 : Npay로 4만원 이상 충전 시 7% 네이버페이 포인트 적립 (최대 4,000원, 중복 불가, 네이버페이 실명 인증 기준 1인 1회 참여 가능)
```

좌표: `chunk_sha256_74f2d3480477b58712eabca88dbd7cbc51263fd9ff55ae1787c51f2885e45a62:285:376`

### accrual_rate

- subject: `Npay 7% 적립 이벤트`
- relation: `accrual_rate`
- value type: `percentage`
- 정답: `[7]`

공식 원문:

```text
■ 이벤트 내용 : Npay로 4만원 이상 충전 시 7% 네이버페이 포인트 적립 (최대 4,000원, 중복 불가, 네이버페이 실명 인증 기준 1인 1회 참여 가능)
```

좌표: `chunk_sha256_74f2d3480477b58712eabca88dbd7cbc51263fd9ff55ae1787c51f2885e45a62:285:376`

### maximum_accrual

- subject: `Npay 7% 적립 이벤트`
- relation: `maximum_accrual`
- value type: `currency`
- 정답: `[{"amount": 4000, "unit": "원"}]`

공식 원문:

```text
■ 이벤트 내용 : Npay로 4만원 이상 충전 시 7% 네이버페이 포인트 적립 (최대 4,000원, 중복 불가, 네이버페이 실명 인증 기준 1인 1회 참여 가능)
```

좌표: `chunk_sha256_74f2d3480477b58712eabca88dbd7cbc51263fd9ff55ae1787c51f2885e45a62:285:376`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 04. 2026년 7월 17일 넥슨 고객상담실 방문 상담은 가능했는지와 전화 상담 운영시간을 알려줘.

- 출처: `dnf_notice`
- 유형: `unsupported_or_partial`
- 기대 응답: `partial_answer`
- 공식 문서: [7/17(금) 넥슨 고객상담실 휴무 안내](https://df.nexon.com/community/news/notice/2928003)

### visit_available

- subject: `2026년 7월 17일 넥슨 고객상담실`
- relation: `visit_available`
- value type: `boolean`
- 정답: `[false]`

공식 원문:

```text
7/17(금)에는 방문 상담 서비스를 이용하실 수 없습니다.
```

좌표: `chunk_sha256_aca71a32f6cd90bf1ce54f7cfccc455fad9f22702cc54d5a0fc730a7a450cff5:99:132`

### telephone_hours

- subject: `2026년 7월 17일 넥슨 고객상담실`
- relation: `telephone_hours`
- value type: `text`
- 정답: `문서 근거 없음(unsupported)`

공식 원문: 없음

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 05. 5월 6일 퍼스트 서버 업데이트 기준 최후의 과업 채널 입장 명성은 얼마였어?

- 출처: `dnf_update`
- 유형: `direct_fact`
- 기대 응답: `full_answer`
- 공식 문서: [5/6(수) 퍼스트 서버 업데이트 안내](https://df.nexon.com/community/news/update/2927233)

### entry_fame

- subject: `최후의 과업 채널`
- relation: `entry_fame`
- value type: `number`
- 정답: `[108921]`

공식 원문:

```text
<최후의 과업> 채널은 모험가 명성 108,921부터 입장이 가능합니다.
```

좌표: `chunk_sha256_ecdae4d23e1593ce7b23038048e3a7adb6feabe70837ae060dde4edbdc2c1ab3:49:89`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 06. 7월 16일 캐릭터 밸런스 패치에서 그래플러(남)와 넨마스터(여)의 스킬 공격력 증가율은 각각 얼마였어?

- 출처: `dnf_update`
- 유형: `sibling_relation`
- 기대 응답: `full_answer`
- 공식 문서: [7/16(목) 정기점검 업데이트 안내](https://df.nexon.com/community/news/update/2927985)

### male_grappler_attack_increase

- subject: `그래플러(남)`
- relation: `attack_increase`
- value type: `percentage`
- 정답: `[12.3]`

공식 원문:

```text
## 그래플러(남)
기본 공격 및 전직 계열 스킬 공격력이 12.3% 증가합니다.
```

좌표: `chunk_sha256_c619a6e414b351eb51ab89e89cfba3c530c3a360ec22f7a343659f665ae54325:47:92`

### female_nenmaster_attack_increase

- subject: `넨마스터(여)`
- relation: `attack_increase`
- value type: `percentage`
- 정답: `[8.8]`

공식 원문:

```text
## 넨마스터(여)
기본 공격 및 전직 계열 스킬 공격력이 8.8% 증가합니다.
```

좌표: `chunk_sha256_9bf8aa31f1803fc7fba9b66119acbdbea0acaa4083fb608fc0b830724b7716dc:0:44`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 07. 5월 6일 퍼스트 서버 업데이트의 최후의 과업 모험도감 ★10 보상과 거래 타입은 뭐였어?

- 출처: `dnf_update`
- 유형: `table_attribute`
- 기대 응답: `full_answer`
- 공식 문서: [5/6(수) 퍼스트 서버 업데이트 안내](https://df.nexon.com/community/news/update/2927233)

### reward

- subject: `최후의 과업 모험도감 ★10`
- relation: `reward`
- value type: `entity`
- 정답: `["신야 대두 아바타 상자"]`

공식 원문:

```text
| ★10 | 신야 대두 아바타 상자 | 계정귀속 |
```

좌표: `chunk_sha256_5a4e1ecd9e3a2244fcd1ed97c6364532e4b975b237861336940652121e764993:162:191`

### trade_type

- subject: `최후의 과업 모험도감 ★10`
- relation: `trade_type`
- value type: `enum`
- 정답: `["계정귀속"]`

공식 원문:

```text
| ★10 | 신야 대두 아바타 상자 | 계정귀속 |
```

좌표: `chunk_sha256_5a4e1ecd9e3a2244fcd1ed97c6364532e4b975b237861336940652121e764993:162:191`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 08. 5월 6일 퍼스트 서버 업데이트 기준 최후의 과업 주간 입장 제한과 통합 보상 횟수는 각각 몇 회였어?

- 출처: `dnf_update`
- 유형: `revision_selection`
- 기대 응답: `full_answer`
- 공식 문서: [5/6(수) 퍼스트 서버 업데이트 안내](https://df.nexon.com/community/news/update/2927233)

### weekly_entry_limit

- subject: `최후의 과업`
- relation: `weekly_entry_limit`
- value type: `number`
- 정답: `[1]`

공식 원문:

```text
| 주간 입장 제한 | 1회 콘텐츠 시작 시 주간 입장 제한 횟수가 차감됩니다. |
```

좌표: `chunk_sha256_cb7eaf5ad1bf639283c236b4e6465c6c0186eed330909ef54629015adfcc2103:135:181`

### integrated_reward_count

- subject: `최후의 과업`
- relation: `integrated_reward_count`
- value type: `number`
- 정답: `[2]`

공식 원문:

```text
| 통합 보상 횟수 | 2회 제한 시간 내 콘텐츠 클리어 시 주간 보상을 획득하실 수 있습니다. 보상 획득 시 통합 보상 횟수는 차감됩니다. 주간 입장 제한 및 통합 보상 횟수는 매주 목요일 06시에 초기화됩니다. |
```

좌표: `chunk_sha256_cb7eaf5ad1bf639283c236b4e6465c6c0186eed330909ef54629015adfcc2103:182:303`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 09. 레바vs낡은창고 드로잉쇼 쿠폰은 계정당 몇 번 입력할 수 있었어?

- 출처: `dnf_event`
- 유형: `direct_fact`
- 기대 응답: `full_answer`
- 공식 문서: [레바vs낡은창고 드로잉쇼 이모티콘](https://df.nexon.com/community/news/event/2927808)

### coupon_input_limit

- subject: `레바vs낡은창고 드로잉쇼 쿠폰`
- relation: `coupon_input_limit`
- value type: `number`
- 정답: `[1]`

공식 원문:

```text
- 모든 쿠폰은 계정당 1회 입력 가능합니다.
```

좌표: `chunk_sha256_5ca681b005815764bfa5c5a38b519fdfbe6d3f07a105feb6c68023c6128c32b4:220:245`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 10. 파도치는 폭권으로! 보급 작전 이벤트 기간은 언제부터 언제까지였어?

- 출처: `dnf_event`
- 유형: `temporal_role`
- 기대 응답: `full_answer`
- 공식 문서: [파도치는 폭권으로! 보급 작전](https://df.nexon.com/pg/newcharsupply)

### event_period

- subject: `파도치는 폭권으로! 보급 작전`
- relation: `event_period`
- value type: `date_range`
- 정답: `["2026-07-02", "2026-07-23"]`

공식 원문:

```text
# 파도치는 폭권으로! 보급 작전 | 이벤트 기간 : 2026년 7월 2일(목) 점검 후 ~ 7월 23일(목) 점검 전
```

좌표: `chunk_sha256_bee29be634f1de5bd63de4f16e54ae7075651958df1b632e68a5d76012d87b68:17:83`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 11. 여름맞이 7일간의 여정 이벤트의 하루 기준(초기화 시각)과 보상 우편 보관 기간은 각각 며칠/몇 시야?

- 출처: `dnf_event`
- 유형: `multi_requirement`
- 기대 응답: `full_answer`
- 공식 문서: [여름맞이 7일간의 여정](https://df.nexon.com/pg/summersevengift)

### daily_boundary_at

- subject: `여름맞이 7일간의 여정`
- relation: `daily_boundary_at`
- value type: `text`
- 정답: `["매일 오전 06시 - 다음날 오전 06시"]`

공식 원문:

```text
본 이벤트의 하루 기준은 매일 오전 06시 - 다음날 오전 06시입니다.
```

좌표: `chunk_sha256_a878bed8d1d723503024f17b25b2641038fcee16dc669147f711f219f6e0b021:120:160`

### mail_retention_days

- subject: `여름맞이 7일간의 여정 보상`
- relation: `mail_retention_days`
- value type: `number`
- 정답: `[15]`

공식 원문:

```text
게임 접속 후 [보상받기]를 클릭하면 보상을 받을 수 있으며, 지급된 보상은 우편함에서 확인 가능합니다. (우편 보관 기간: 15일)
```

좌표: `chunk_sha256_a878bed8d1d723503024f17b25b2641038fcee16dc669147f711f219f6e0b021:247:321`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 12. 트리니티 이벤트의 일반모드 플레이도 랭킹 집계에 포함됐어?

- 출처: `dnf_event`
- 유형: `boolean_direction`
- 기대 응답: `full_answer`
- 공식 문서: [트리니티](https://df.nexon.com/pg/trinity)

### normal_mode_counted

- subject: `트리니티 일반모드`
- relation: `ranked`
- value type: `boolean`
- 정답: `[false]`

공식 원문:

```text
- 랭킹은 챌린지모드 3종의 몬스터를 모두 처치 시에만 집계 합니다. (일반모드는 랭킹 집계와 무관합니다.)
```

좌표: `chunk_sha256_b6078258f48df06c1ecb28cf78781bbb258bc6c1fee092d82835aa0464b39af6:123:183`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 13. 성장 가속 모드 상태의 캐릭터로 결투장을 이용할 수 있어?

- 출처: `dnf_faq`
- 유형: `boolean_direction`
- 기대 응답: `full_answer`
- 공식 문서: [[게임 이용] 성장 가속 모드 캐릭터로 결투장에 입장하고 싶어요.](https://df.nexon.com/customer/faq?faq_no=4998)

### duel_arena_available

- subject: `성장 가속 모드 캐릭터`
- relation: `duel_arena_available`
- value type: `boolean`
- 정답: `[false]`

공식 원문:

```text
아쉽게도 성장 가속 모드 상태에서는 결투장 이용이 어렵습니다.
```

좌표: `chunk_sha256_3f4f24ea7ed23714c0c4a16147263fa0cb43f9420243a79c2de2d6bde6fdda4f:37:71`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 14. 세라 충전한도는 마이페이지에서 어떤 경로로 변경할 수 있어?

- 출처: `dnf_faq`
- 유형: `direct_fact`
- 기대 응답: `full_answer`
- 공식 문서: [[결제 한도] 세라 충전한도 초과 메시지가 나와요.](https://df.nexon.com/customer/faq?faq_no=4963)

### settings_path

- subject: `세라 충전한도`
- relation: `settings_path`
- value type: `text`
- 정답: `["마이페이지 → 세라 관리 → 세라 충전한도 설정 및 확인"]`

공식 원문:

```text
위 링크 또는 (마이페이지 → 세라 관리 → 세라 충전한도 설정 및 확인)에서 확인하실 수 있습니다.
```

좌표: `chunk_sha256_54ecf7ab5c05b9c023fb513d59895cd144ef22c76f673d289a10100577c2027c:128:184`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 15. 네오플OTP 에러 코드 22를 해결할 때 재설치 후 안드로이드와 iOS에서 각각 어떤 시간 설정을 해야 해?

- 출처: `dnf_faq`
- 유형: `sibling_relation`
- 기대 응답: `full_answer`
- 공식 문서: [[네오플OTP] OTP 가입 시도 시 "에러 코드 22"가 나와요.](https://df.nexon.com/customer/faq?faq_no=4922)

### android_time_setting

- subject: `네오플OTP 에러 코드 22 안드로이드`
- relation: `time_sync_setting`
- value type: `text`
- 정답: `["OTP 실행 → 좌측 상단 버튼 누른 후 시간설정 → 시간 동기화"]`

공식 원문:

```text
⑥ (재설치 후) OTP 실행 → 좌측 상단 버튼 누른 후 시간설정 → 시간 동기화
```

좌표: `chunk_sha256_ec70c32aa82a44d9fae38a06ca23ac33f7677537e857996c51132f9746cc1842:217:263`

### ios_time_setting

- subject: `네오플OTP 에러 코드 22 iOS`
- relation: `time_sync_setting`
- value type: `text`
- 정답: `["설정 → 일반 → 날짜와시간 → 자동으로 설정 체크"]`

공식 원문:

```text
⑥ (재설치 후) 설정 → 일반 → 날짜와시간 → 자동으로 설정 체크
```

좌표: `chunk_sha256_ec70c32aa82a44d9fae38a06ca23ac33f7677537e857996c51132f9746cc1842:375:413`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 16. 장착 칭호가 해제되지 않을 때 1:1 문의에 적어야 할 정보와 평균 처리 기간을 알려줘.

- 출처: `dnf_faq`
- 유형: `unsupported_or_partial`
- 기대 응답: `partial_answer`
- 공식 문서: [[게임 이용] 장착중인 칭호가 해제되지 않아요!](https://df.nexon.com/customer/faq?faq_no=4986)

### required_inquiry_fields

- subject: `장착 칭호 해제 1:1 문의`
- relation: `required_inquiry_fields`
- value type: `entity_list`
- 정답: `["서버", "캐릭터명", "장착중인 칭호"]`

공식 원문:

```text
[기재사항]
1. 서버/캐릭터명 :
2. 장착중인 칭호 :
```

좌표: `chunk_sha256_a8f6f9b72eac50f6cc41586d84b6da03b9781cc7b0b35923c479994e9291bff8:131:163`

### average_processing_time

- subject: `장착 칭호 해제 1:1 문의`
- relation: `average_processing_time`
- value type: `text`
- 정답: `문서 근거 없음(unsupported)`

공식 원문: 없음

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 17. 위업의 기억에서 캐릭터 귀속은 매월 언제 해제돼?

- 출처: `dnf_game_guide`
- 유형: `direct_fact`
- 기대 응답: `full_answer`
- 공식 문서: [[115] 위업의 기억](https://df.nexon.com/guide?no=1490)

### binding_reset_at

- subject: `위업의 기억 캐릭터 귀속`
- relation: `binding_reset_at`
- value type: `text`
- 정답: `["매월 1일 오전 06시"]`

공식 원문:

```text
| 월간 초기화 | 매월 1일 오전 06시에 캐릭터 귀속 해제 매 달 모든 캐릭터는 다음 달 1티어로 조정 입장 명성 달성 시 이전 클리어 기록과 상관 없이 입장 가능 |
```

좌표: `chunk_sha256_e1f0452ebca1b1cee1d4cf33a56d89d32cfdbc4b3ec8bf707d2440ac1eb7b8cf:448:543`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 18. 광휘의 순례 배니부 상점의 유니크 아티팩트 레시피 거래 속성은 뭐야?

- 출처: `dnf_game_guide`
- 유형: `table_attribute`
- 기대 응답: `full_answer`
- 공식 문서: [[던전] 배낭지기 배니부 상점](https://df.nexon.com/guide?no=1482)

### trade_type

- subject: `광휘의 순례 배니부 상점 유니크 아티팩트 레시피`
- relation: `trade_type`
- value type: `enum`
- 정답: `["계정귀속"]`

공식 원문:

```text
| 유니크 아티팩트 레시피 | 아이템명에 해당하는 유니크 아티팩트를 100% 확률로 제작합니다. 제작된 아이템은 밀봉 상태로 제공됩니다. | 계정귀속 |
```

좌표: `chunk_sha256_3506cfc35117445fc7ce08f38d389518df52fd2fb6bcd115d67e411d40db27ca:197:282`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 19. 금고 재료 사용 기능은 상점에서 어떻게 켜고, 재료는 어느 두 금고에 있어도 사용할 수 있어?

- 출처: `dnf_game_guide`
- 유형: `multi_requirement`
- 기대 응답: `full_answer`
- 공식 문서: [금고 재료 사용](https://df.nexon.com/guide?no=1427)

### activation_method

- subject: `금고 재료 사용 기능`
- relation: `activation_method`
- value type: `text`
- 정답: `["상점 메뉴에서 '구매 시, 금고 재료 사용'을 클릭하여 활성화"]`

공식 원문:

```text
상점 메뉴에서 '구매 시, 금고 재료 사용'을 클릭하여 활성화 합니다.
```

좌표: `chunk_sha256_ecb150fd11cbc615b6a876c69775da625eca29d7f89d1e99d8ac7363a00db2c9:10:49`

### supported_vaults

- subject: `금고 재료 사용 기능`
- relation: `supported_vaults`
- value type: `entity_list`
- 정답: `["내 금고", "계정 금고"]`

공식 원문:

```text
내 금고나 계정 금고에 아이템이 보관되어 있는 경우, 구매 시도 시 재료 사용 동의 메뉴가 등장합니다.
```

좌표: `chunk_sha256_ecb150fd11cbc615b6a876c69775da625eca29d7f89d1e99d8ac7363a00db2c9:50:107`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 20. 칼레이도 박스와 마스터 칼레이도 박스는 장비 품질을 각각 어떻게 바꿔?

- 출처: `dnf_game_guide`
- 유형: `sibling_relation`
- 기대 응답: `full_answer`
- 공식 문서: [아이템 등급](https://df.nexon.com/guide?no=1238)

### regular_quality_result

- subject: `칼레이도 박스`
- relation: `quality_result`
- value type: `text`
- 정답: `["최하급에서 최상급 사이로 랜덤"]`

공식 원문:

```text
칼레이도 박스를 사용하면 장비 아이템 품질을 최하급에서 최상급 사이로 랜덤하게 설정할 수 있습니다.
```

좌표: `chunk_sha256_84cf83f9b9f8a77653d84f8ced6e7e3824202903648d2f1f32a78f17ac98a1bd:19:74`

### master_quality_result

- subject: `마스터 칼레이도 박스`
- relation: `quality_result`
- value type: `percentage`
- 정답: `[100]`

공식 원문:

```text
마스터 칼레이도 박스를 사용할 경우, 확정적으로 아이템 품질을 100%로 변환할 수 있습니다.
```

좌표: `chunk_sha256_3c1761cc6471cb4da87b480e765c1a1dcf309e5c7cf4410eaae9aaf819e1907f:26:78`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 21. 2023년 6월 10일 시행 운영정책에서 휴면ID 전환 기준은 몇 개월 미접속이었어?

- 출처: `dnf_account_policy`
- 유형: `revision_selection`
- 기대 응답: `full_answer`
- 공식 문서: [던전앤파이터 운영정책 (2023-06-10 시행)](https://df.nexon.com/customer/policy/home?revision=2023-06-10&type=1)

### inactive_months

- subject: `2023년 6월 10일 시행 운영정책 휴면ID`
- relation: `inactive_months`
- value type: `number`
- 정답: `[12]`

공식 원문:

```text
① 12개월 이상 접속 기록이 없는 경우 휴면ID로 전환하여 관리됩니다.
```

좌표: `chunk_sha256_dbc307fc7c03fea15e773056aae843fbc01c19e238d052ae41d372d347505fb3:223:263`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 22. 2022년 8월 4일 시행 운영정책에서는 비정상 재화를 받은 사람이 고의나 인지 여부와 무관하게 재화를 회수할 수 있었어?

- 출처: `dnf_account_policy`
- 유형: `boolean_direction`
- 기대 응답: `full_answer`
- 공식 문서: [던전앤파이터 운영정책 (2022-08-04 시행)](https://df.nexon.com/customer/policy/home?revision=2022-08-04&type=1)

### recoverable_regardless_of_awareness

- subject: `2022년 8월 4일 시행 운영정책 비정상 재화`
- relation: `recoverable_regardless_of_awareness`
- value type: `boolean`
- 정답: `[true]`

공식 원문:

```text
[4-4-3] 버그, 시스템 취약점 공격, 비인가 프로그램 사용, 계정도용 등 비정상적으로 생성되거나 이동된 재화(이하 “비정상 재화”)는 고의 여부, 인지 여부와 상관없이 회수됩니다.
```

좌표: `chunk_sha256_2d7f0e5a67043423286a292d9c622da7f2807c3d286810ee7f05b726d23b684f:971:1074`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 23. 2021년 1월 21일 시행 운영정책에서 운영자·직원 사칭과 허위사실 유포의 1차 이용제한은 각각 며칠이었어?

- 출처: `dnf_account_policy`
- 유형: `sibling_relation`
- 기대 응답: `full_answer`
- 공식 문서: [던전앤파이터 운영정책 (2021-01-21 시행)](https://df.nexon.com/customer/policy/home?revision=2021-01-21&type=1)

### impersonation_first_penalty

- subject: `운영자·직원 사칭`
- relation: `first_penalty`
- value type: `duration`
- 정답: `[{"amount": 100, "unit": "일"}]`

공식 원문:

```text
| 운영자 / 직원을 사칭하는 행위 | 계정100일 이용제한 | 계정1년 이용제한 | 계정3년 이용제한 | 계정영구 이용제한 |
```

좌표: `chunk_sha256_bf4b3da3a482ff1960490ea8a302fd55f1276ad4cec17f21ebe35424307d8fc6:755:826`

### false_information_first_penalty

- subject: `허위사실 유포·제보`
- relation: `first_penalty`
- value type: `duration`
- 정답: `[{"amount": 10, "unit": "일"}]`

공식 원문:

```text
| 허위사실 유포, 제보 | 계정10일 이용제한 | 계정30일 이용제한 | 계정100일 이용제한 | 계정영구 이용제한 |
```

좌표: `chunk_sha256_bf4b3da3a482ff1960490ea8a302fd55f1276ad4cec17f21ebe35424307d8fc6:827:894`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 24. 2020년 12월 4일 시행 운영정책에서 길드장 권한이 위임될 수 있는 조건과 처리 기간을 알려줘.

- 출처: `dnf_account_policy`
- 유형: `unsupported_or_partial`
- 기대 응답: `partial_answer`
- 공식 문서: [던전앤파이터 운영정책 (2020-12-04 시행)](https://df.nexon.com/customer/policy/home?revision=2020-12-04&type=1)

### delegation_conditions

- subject: `길드장 권한 위임`
- relation: `delegation_conditions`
- value type: `entity_list`
- 정답: `["길드장 계정이 이용제한 상태", "길드장 계정이 12개월 이상 미접속으로 인한 휴면 상태"]`

공식 원문:

```text
길드장 임의 교체는 가능하지 않습니다. 단, 아래의 사유에 해당할 경우에는 길드장 권한이 다른 길드원에게 위임될 수 있습니다.
① 길드장 계정이 이용제한 상태인 경우
② 길드장 계정이 12개월이상 미접속으로 인한 휴면 상태인 경우
```

좌표: `chunk_sha256_b9c48471a3d9e635c17dc2e3a7240be676f21270c3837739df661eee37a67bc7:1669:1797`

### processing_time

- subject: `길드장 권한 위임`
- relation: `processing_time`
- value type: `duration`
- 정답: `문서 근거 없음(unsupported)`

공식 원문: 없음

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 25. 마일리지샵 2026 시즌4의 향상된 럭키 박스 3단계 가격, 구매 조건, 거래 타입은 뭐였어?

- 출처: `dnf_seria_shop`
- 유형: `table_attribute`
- 기대 응답: `full_answer`
- 공식 문서: [마일리지샵 2026 시즌 4](https://df.nexon.com/community/news/seriashop/613)

### price

- subject: `향상된 럭키 박스 3단계`
- relation: `price`
- value type: `currency`
- 정답: `[{"amount": 150, "unit": "M"}]`

공식 원문:

```text
| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) | [M] 향상된 럭키 박스 (3 단계 ) |
| 아이콘 | | | |
| 가격 | 100M | 120M | 150M |
| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |
| 거래타입 | 계정귀속 | 계정귀속 | 계정귀속 |
```

좌표: `chunk_sha256_ab1acd6a019e1d2f224f6c68b9bcb272deb1de7e8b105d4ec7210536ec01af1f:92:330`

### purchase_condition

- subject: `향상된 럭키 박스 3단계`
- relation: `purchase_condition`
- value type: `text`
- 정답: `["하루 1개 구매 가능, 2단계 구매 후 구매 가능"]`

공식 원문:

```text
| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) | [M] 향상된 럭키 박스 (3 단계 ) |
| 아이콘 | | | |
| 가격 | 100M | 120M | 150M |
| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |
| 거래타입 | 계정귀속 | 계정귀속 | 계정귀속 |
```

좌표: `chunk_sha256_ab1acd6a019e1d2f224f6c68b9bcb272deb1de7e8b105d4ec7210536ec01af1f:92:330`

### trade_type

- subject: `향상된 럭키 박스 3단계`
- relation: `trade_type`
- value type: `enum`
- 정답: `["계정귀속"]`

공식 원문:

```text
| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) | [M] 향상된 럭키 박스 (3 단계 ) |
| 아이콘 | | | |
| 가격 | 100M | 120M | 150M |
| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |
| 거래타입 | 계정귀속 | 계정귀속 | 계정귀속 |
```

좌표: `chunk_sha256_ab1acd6a019e1d2f224f6c68b9bcb272deb1de7e8b105d4ec7210536ec01af1f:92:330`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 26. 2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자의 판매 기간과 일괄 삭제 시각은 언제였어?

- 출처: `dnf_seria_shop`
- 유형: `temporal_role`
- 기대 응답: `full_answer`
- 공식 문서: [2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자](https://df.nexon.com/community/news/seriashop/614)

### sale_period

- subject: `2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자`
- relation: `sale_period`
- value type: `date_range`
- 정답: `["2026-04-09", "2026-06-04"]`

공식 원문:

```text
- 2026 년 04 월 09 일 점검 후부터 2026 년 06 월 04일 점검 전까지 세라샵 > 패키지 > 전체 카테고리에서 만나보실 수 있습니다 .
```

좌표: `chunk_sha256_689f4f387f41b3cdf590ac997497c91f78167f962811d0755ff3771ecd635796:200:284`

### deletion_at

- subject: `2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자 및 구성품`
- relation: `deletion_at`
- value type: `datetime`
- 정답: `["2026-06-04T06:00:00+09:00"]`

공식 원문:

```text
- 2026 아라드 패스 꿈 속의 던토피아 아바타 콤보 상자 및 구성 품은 2026년 06월 04일 06시 일괄 삭제됩니다.
```

좌표: `chunk_sha256_689f4f387f41b3cdf590ac997497c91f78167f962811d0755ff3771ecd635796:285:354`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 27. 2026 DNF 폴리스 아바타 콤보 상자의 가격과 구매 시 받는 두 상자는 뭐였어?

- 출처: `dnf_seria_shop`
- 유형: `multi_requirement`
- 기대 응답: `full_answer`
- 공식 문서: [2026 DNF 폴리스 아바타 콤보 상자](https://df.nexon.com/community/news/seriashop/603)

### price

- subject: `2026 DNF 폴리스 아바타 콤보 상자`
- relation: `price`
- value type: `currency`
- 정답: `[{"amount": 12900, "unit": "세라"}]`

공식 원문:

```text
- 교환가능 아이템 : 12,900 세라
```

좌표: `chunk_sha256_58616d57520cb9854af309342380095243ba4195f106c108cd717670490aae5d:25:47`

### included_boxes

- subject: `2026 DNF 폴리스 아바타 콤보 상자`
- relation: `included_boxes`
- value type: `entity_list`
- 정답: `["2026 DNF 폴리스 아바타 풀세트 상자", "2026 DNF 폴리스 보너스 상자"]`

공식 원문:

```text
- 아바타 콤보 상자 구매 시 , 2026 DNF 폴리스 아바타 풀세트 상자 와 2026 DNF 폴리스 보너스 상자 를 얻을 수 있습니다.
```

좌표: `chunk_sha256_58616d57520cb9854af309342380095243ba4195f106c108cd717670490aae5d:48:125`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 28. 2026년 1월 해방의 열쇠 100개 상자의 판매 기간과, 상자에서 나온 해방의 열쇠 거래 타입은 뭐였어?

- 출처: `dnf_seria_shop`
- 유형: `revision_selection`
- 기대 응답: `full_answer`
- 공식 문서: [해방의 열쇠 100개 상자](https://df.nexon.com/community/news/seriashop/595)

### sale_period

- subject: `2026년 1월 해방의 열쇠 100개 상자`
- relation: `sale_period`
- value type: `date_range`
- 정답: `["2026-01-01", "2026-01-15"]`

공식 원문:

```text
26년 1월 1일 00시 ~ 1월 15일 점검 전 까지 판매하는 해방의 열쇠 100개 상자 소개와 함께 주의사항을 안내 드리겠습니다.
```

좌표: `chunk_sha256_98751322f4c3c11ce60ba45cc14e0a486ffa758df4c242c401e3422399355c69:188:262`

### key_trade_type

- subject: `2026년 1월 해방의 열쇠 100개 상자에서 획득한 해방의 열쇠`
- relation: `trade_type`
- value type: `enum`
- 정답: `["교환불가"]`

공식 원문:

```text
| 툴팁 | 사용 시 해방의 열쇠 100개, 봉인된 자물쇠 34개를 획득할 수 있습니다. 해방의 열쇠는 교환불가, 기간 무제한 아이템입니다. |
```

좌표: `chunk_sha256_e08795dc0b802a70da881bebab2aa78ff6e2958f547c0d0566abdab23e4853d8:93:173`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 29. 2025년 12월 스페셜 클론 레어 아바타 풀세트 상자의 상점 판매가격과 거래 타입은 뭐였어?

- 출처: `dnf_monthly_item`
- 유형: `table_attribute`
- 기대 응답: `full_answer`
- 공식 문서: [12월 이달 의 아이템](https://df.nexon.com/community/news/seriashop/587)

### shop_price

- subject: `2025년 12월 스페셜 클론 레어 아바타 풀세트 상자`
- relation: `shop_price`
- value type: `currency`
- 정답: `[{"amount": 40000000, "unit": "골드"}]`

공식 원문:

```text
# [12월 이달의 아이템] : [12월]스페셜 클론 레어 아바타 풀세트 상자
[TABLE]
| 구분 | 이달의 아이템 |
| 아이템명 | [12월]스페셜 클론 레어 아바타 풀세트 상자 |
| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |
| 상점판매가격 | 4,000만 골드 |
| 거래타입 | 교환가능 |
```

좌표: `chunk_sha256_6a493e465882581fc2ec1f31a7b11cbfd768d274da2e116b570e5feb56b812de:0:187`

### trade_type

- subject: `2025년 12월 스페셜 클론 레어 아바타 풀세트 상자`
- relation: `trade_type`
- value type: `enum`
- 정답: `["교환가능"]`

공식 원문:

```text
# [12월 이달의 아이템] : [12월]스페셜 클론 레어 아바타 풀세트 상자
[TABLE]
| 구분 | 이달의 아이템 |
| 아이템명 | [12월]스페셜 클론 레어 아바타 풀세트 상자 |
| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |
| 상점판매가격 | 4,000만 골드 |
| 거래타입 | 교환가능 |
```

좌표: `chunk_sha256_6a493e465882581fc2ec1f31a7b11cbfd768d274da2e116b570e5feb56b812de:0:187`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 30. 2025년 11월 시브의 보조장비 보주는 삭제 기한이 정해져 있었어?

- 출처: `dnf_monthly_item`
- 유형: `temporal_role`
- 기대 응답: `full_answer`
- 공식 문서: [11월 이달 의 아이템](https://df.nexon.com/community/news/seriashop/586)

### has_deletion_deadline

- subject: `2025년 11월 시브의 보조장비 보주`
- relation: `has_deletion_deadline`
- value type: `boolean`
- 정답: `[false]`

공식 원문:

```text
# [11월 이달의 아이템] : 시브의 보조장비 보주
[TABLE]
| 구분 | 이달의 아이템 |
| 아이템명 | 시브의 보조장비 보주 |
| 아이콘 | |
| 상점판매가격 | 4,000만 골드 |
| 거래타입 | 1회 교환가능(거래 후 계정귀속) |
| 툴팁 | 모든 속성 강화 +12 물리 크리티컬 히트 +3% 마법 크리티컬 히트 +3% 공격력 증폭 +3% 모험가 명성 +221 |
| 삭제일자 | 무제한 |
```

좌표: `chunk_sha256_97fe7e1eaf927e4bc6271c9e747500636a36e96ef22938ffe25fd2625b8d0ae3:0:230`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 31. 2026년 6월 찬란한 엠블렘 풀세트 선택상자에서는 선택한 한 종류의 엠블렘을 몇 개 받았어?

- 출처: `dnf_monthly_item`
- 유형: `revision_selection`
- 기대 응답: `full_answer`
- 공식 문서: [6월 이달 의 아이템](https://df.nexon.com/community/news/seriashop/622)

### selected_emblem_quantity

- subject: `2026년 6월 찬란한 엠블렘 풀세트 선택상자`
- relation: `selected_emblem_quantity`
- value type: `number`
- 정답: `[4]`

공식 원문:

```text
# [6월 이달의 아이템] : [6월]스페셜 클론 레어 아바타 풀세트 상자
[TABLE]
| 구분 | 이달의 아이템 |
| 아이템명 | [6월]스페셜 클론 레어 아바타 풀세트 상자 |
| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |
| 상점판매가격 | 4,000만 골드 |
| 거래타입 | 교환가능 |
| 툴팁 | 사용 시 [6월]클론 레어 아바타(교환불가) 풀세트 상자와 [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자를 얻을 수 있습니다. [6월]클론 레어 아바타(교환불가) 풀세트 상자, [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자는 교환가능 아이템입니다. [6월]클론 레어 아바타(교환불가)풀세트 상자 사용 시 클론 레어 아바타(교환불가) 풀세트를 획득할 수 있습니다. [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자를 사용하여 획득한 엠블렘은 계정귀속, 합성불가 타입이며 교환불가 아바타에만 장착할 수 있습니다. 획득한 모든 아이템은 2026년 7월 9일 06시 일괄 삭제됩니다. |
| 삭제일자 | 2026년 7월 9일 06시 일괄삭제 |
[/TABLE]
* 스페셜 클론 레어 아바타 풀세트 상자 구성품
[TABLE]
| 구분 | 스페셜 클론 레어 아바타 풀세트 상자 구성품 |
| 아이템명 | [6월]클론 레어 아바타(교환불가) 풀세트 상자 | [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자 |
| 아이콘 | [IMAGE_ALT] 클론 레어 아바타(교환불가) 풀세트 상자 | [IMAGE_ALT] 찬란한 엠블렘(계정귀속) 풀세트 선택상자 |
| 거래타입 | 교환가능 | 교환가능 |
| 툴팁 | 클론 레어 아바타(교환불가) 8부위를 받을 수 있습니다. | 찬란한 붉은빛 엠블렘 상자, 찬란한 노란빛 엠블렘 상자, 찬란한 녹색빛 엠블렘 상자, 찬란한 푸른빛 엠블렘 상자를 얻을 수 있습니다. 엠블렘 상자는 계정귀속 아이템으로 제공됩니다. 엠블렘 상자를 사용하여 획득한 엠블렘은 계정귀속, 합성불가이며 교환불가 아바타에만 장착할 수 있습니다. 획득한 엠블렘은 2026년 7월 9일 06시에 일괄 삭제됩니다. |
| 삭제일자 | 2026년 7월 9일 06시 일괄삭제 | 2026년 7월 9일 06시 일괄삭제 |
[/TABLE]
- [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자에서 선택 가능한 엠블렘 목록입니다.
- 선택한 한 종류의 엠블렘 4개를 획득할 수 있습니다.
```

좌표: `chunk_sha256_6ca94020f0661c022cf19032640d142d7c07b4e1c0a29f21bc9bf908059ba95b:0:1182`

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:

## 32. 2026년 5월 고대의 바인드 큐브 8개 상자의 거래 타입과 계정당 구매 제한을 알려줘.

- 출처: `dnf_monthly_item`
- 유형: `unsupported_or_partial`
- 기대 응답: `partial_answer`
- 공식 문서: [5월 이달 의 아이템](https://df.nexon.com/community/news/seriashop/619)

### trade_type

- subject: `2026년 5월 고대의 바인드 큐브 8개 상자`
- relation: `trade_type`
- value type: `enum`
- 정답: `["교환가능"]`

공식 원문:

```text
# [5월 이달의 아이템] : 고대의 바인드 큐브 8개 상자
[TABLE]
| 구분 | 이달의 아이템 |
| 아이템명 | 고대의 바인드 큐브 8개 상자 |
| 아이콘 | |
| 상점판매가격 | 4,000만 골드 |
| 거래타입 | 교환가능 |
```

좌표: `chunk_sha256_c857f86c47478e2ab0aab54f63e08bd56313c08235f9a605f857e4d91bbdf53b:0:135`

### account_purchase_limit

- subject: `2026년 5월 고대의 바인드 큐브 8개 상자`
- relation: `account_purchase_limit`
- value type: `text`
- 정답: `문서 근거 없음(unsupported)`

공식 원문: 없음

- [ ] 질문 표현 승인
- [ ] 정답 값 승인
- [ ] 원문 근거·좌표 승인
- 검수 메모:
