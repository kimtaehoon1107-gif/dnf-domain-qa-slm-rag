# Question-partial context answer-unit A/B

Development-only. Gold is used only for scoring and the direct-data audit.
No runtime or canonical promotion was performed.

## Result

| Metric | Arm Q2 | Arm Q3 |
|---|---:|---:|
| Correct mixed partial | 12/13 | 12/13 |
| Span-strict mixed partial | 9/13 | 12/13 |
| Overclaim | 0/13 | 0/13 |
| Missing official evidence | 1/13 | 1/13 |

Decision: **DEVELOPMENT_GO_CONTEXT_ARM_RUNTIME_NOT_PROMOTED**. Context was applied to 12 cases; one retrieval/partial-signal case remains.

## Direct failure audit

### authored_canary_sha256_2da2c7cab1f609754b2910c8e7f168b7f140b0b41a54a503c5e63f9e18fa0995

Question: 과실복구 신청 경로와 작성할 내용을 알려주고, 내 실수가 복구 대상인지 판정해줘.

Type: `SAME_CHUNK_CONTEXT_TRUNCATION`; Q3 fixed: `True`.

모든 gold chunk는 이미 인용했지만 선택 span이 청크 안의 후속 값·목록을 포함하지 않았다. 동일 청크 context answer-unit으로 복구된다.

Q2 claims:

- `chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7` — 📮 던전앤파이터 과실복구 신청 방법
이용 중 실수가 발생 하셨나요? 던전앤파이터 과실복구 신청 방법에 대해 안내 드립니다. ​
STEP.1) 과실복구 신청을 위해서는 [복구신청 접수하기] 버튼을 클릭해서 문의해 주셔야 합니다.
1:1 문의 작성으로 신청하는 경우 복구가 진행되지 않으니 배너 클릭 후 '과실복구 신청' 통한 문의접수 부탁 드립니다.
​

Gold evidence spans:

- `evidence_1` — STEP.1) 과실복구 신청을 위해서는 [복구신청 접수하기] 버튼을 클릭해서 문의해 주셔야 합니다.
- `evidence_2` — STEP.2) 신속하고 정확한 복구 처리를 위해 요청사항을 명확히 기재해 주시기 바랍니다.

Chosen sources: `['dnf_faq']`; candidate sources: `['dnf_faq', 'dnf_notice', 'dnf_game_guide', 'dnf_account_policy']`.
Answerability signal: `partial` (official_fact_plus_personal_judgment).

### authored_canary_sha256_9e2c7f69dd204fd5229a8e21b441b7d2c07b3e4ba5eb73ee5b40f5867f4bb875

Question: 마일리지샵 시즌7에서 마일리지 소멸 시점과 일일 획득 한도를 알려주고, 내 마일리지가 몇 남을지 계산해줘.

Type: `SOURCE_SCOPE_PLUS_PARTIAL_SIGNAL_MISS`; Q3 fixed: `False`.

hard source route가 gold source를 후보에서 제외했고 question-level partial signal도 개인 계산 요구를 놓쳤다. 기존 federated 진단은 근거만 회수한다.

Q2 claims:

- `chunk_sha256_0cc2354d72cd2a5519824cf9c4c500901ad796798a46d0b33d681df45253283e` — 150M |
| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |
| 거래타입 | 계정귀속 | 계정귀속

Gold evidence spans:

- `evidence_1` — - 던전/레이드/결투장을 통해 획득 가능한 마일리지는 일일 최대 50M입니다.
- `evidence_2` — - 획득한 마일리지는 시즌이 종료되는 2026년 8월 27일(목) 06시에 소멸됩니다.

Chosen sources: `['dnf_seria_shop']`; candidate sources: `['dnf_seria_shop', 'dnf_event', 'dnf_notice', 'dnf_game_guide', 'dnf_faq']`.
Answerability signal: `true` (official_document_fact_request).

### retrieval_dev_sha256_144296d937ab23d899b3375c994f2e6568b4a9febb2beb18a68de0a89465c047

Question: 보급 작전 보상 보면 브레이커 키우는 게 내 계정에 제일 좋아?

Type: `SAME_CHUNK_CONTEXT_TRUNCATION`; Q3 fixed: `True`.

모든 gold chunk는 이미 인용했지만 선택 span이 청크 안의 후속 값·목록을 포함하지 않았다. 동일 청크 context answer-unit으로 복구된다.

Q2 claims:

- `chunk_sha256_fa0d7d32cb6a6e4787dd167c86131ab3e9dc7fbbcf323f735937322f1341c8a6` — ## 보급품 안내
회로도
이벤트 보러가기
단계별 보상 설명 자세히 보기
모험가님, 꼭 확인해주세요!
[공통]
- 본 이벤트는 계정 단위로 참여 가능합니다.
[미션]

Gold evidence spans:

- `evidence_1` — 보너스 창고의 보급품은 브레이커 혹은 인파이터(여)만 사용할 수 있습니다. 단, 보너스 보급품은 모든 캐릭터에서 사용 가능합니다.

### retrieval_dev_sha256_bad06d84865648fcf4702d7117102cf68d11f24f448dcee9b9ca14c623e90f1d

Question: 오라클 탐사 지원의 기초 데이터를 얻을 수 있는 던전을 설명해주면서, 내 캐릭터는 어디를 도는 게 좋을지도 골라줘?

Type: `SAME_CHUNK_CONTEXT_TRUNCATION`; Q3 fixed: `True`.

모든 gold chunk는 이미 인용했지만 선택 span이 청크 안의 후속 값·목록을 포함하지 않았다. 동일 청크 context answer-unit으로 복구된다.

Q2 claims:

- `chunk_sha256_53e2ad7eb623236ec43257983115ba0c1168afa00986769d34f67ff4ff00867c` — - 천칭 시뮬레이션 진행도를 100% 달성 시 다음 시뮬레이션에 도전할 수 있습니다.
- 천칭 시뮬레이션은 반복하여 도전할 수 있으며, 시뮬레이션을 새로 진행할 때 마다 필요한 기초 데이터의 개수가 증가합니다.
- 천칭 시뮬레이션 진행도는 매주 목요일 06시 초기화됩니다.
- 1회차와 나머지 회차의 보상은 동일하지 않습니다.
- 천칭 시뮬레이션 진행도 보상은 캐릭터 인벤토리로 지급됩니다.
[히든 상점]
- Dr.오라클의 히든 상점은 최후의 조율자와 천해를 품은 하늘(계시 : 천해를 품은 하늘 던전 포함) 던전 클리어 시 정해진 확률로 등장합니다.

Gold evidence spans:

- `evidence_1` — * 천해천 적정 레벨 던전 : 조율의 경계/최후의 조율자/천해를 품은 하늘 (계시 : 천해를 품은 하늘 던전 포함) * 상급 던전 : 달이 잠긴 호수/애쥬어 메인/죽음의 여신전/해방된 흉몽(챌린지 제외)/별거북 대서고/배교자의 성/최후의 과업 - 시나리오 던전 및 일부 특수 던전에서는 기초 데이터가 드랍되지 않습니다
