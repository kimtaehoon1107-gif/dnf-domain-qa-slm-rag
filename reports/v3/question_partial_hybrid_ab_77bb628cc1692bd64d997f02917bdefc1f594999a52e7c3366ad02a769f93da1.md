# Mixed-answerability errors and question-partial hybrid A/B

Development-only direct-data audit. Gold appears only in this audit and scoring;
Arm Q2 decisions use no gold, new keyword, model call, or per-question rule.

## A/B result

| Metric | Arm 0 | Arm Q | Arm Q2 |
|---|---:|---:|---:|
| Correct mixed partial | 2/13 | 10/13 | 12/13 |
| Span-strict mixed partial | 2/13 | 7/13 | 9/13 |
| Mixed over-claim | 10/13 | 0/13 | 0/13 |
| Mixed missing evidence | 1/13 | 3/13 | 1/13 |

Decision: **DEVELOPMENT_GO_CANDIDATE**. Source counts: `{'frozen_arm0_already_partial': 2, 'frozen_authored_canary_first_run': 3, 'frozen_canonical_claim_reranker_v3_1': 7}`.

## Direct error cases

### 1. 7월 16일 확인된 화면 표시 오류의 처리 상태를 알려주고, 내 PC에서도 다시 생길지 판단해줘.

- case: `authored_canary_sha256_09d9774ed3e7ac99faddfd10bd2c6bb0d52fc29088570a850641700e6937f337`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 화면 표시 오류의 공식 처리 상태**

`chunk_sha256_094cb6d9ce0956dfa794a293089807dbc2131540becb8aa51d24fc7fa3d28df6`

```text
(15:06 추가) 7/16(목) 확인된 오류 안내
```

`chunk_sha256_cde17b10d26f9feed2762130d32d6835595d8bf695c1b307ce8bdf2559cfe2d8`

```text
| 내용 | * 서버 안정화를 위한 네트워크 점검 * 7/16 정기점검 업데이트 적용 |
```

`chunk_sha256_54509891503999ee48ab645d7562fd918df16599c5ef60a6ed35ebe1d8eb299b`

```text
▒ 오류 현상
```

**R2 · docs=false · 사용자 PC에서의 재발 가능성 판단**

`chunk_sha256_094cb6d9ce0956dfa794a293089807dbc2131540becb8aa51d24fc7fa3d28df6`

```text
(15:06 추가) 7/16(목) 확인된 오류 안내
```

`chunk_sha256_54509891503999ee48ab645d7562fd918df16599c5ef60a6ed35ebe1d8eb299b`

```text
▒ 오류 현상
```

`chunk_sha256_cde17b10d26f9feed2762130d32d6835595d8bf695c1b307ce8bdf2559cfe2d8`

```text
| 날짜 | 2026년 7월 16일 |
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_094cb6d9ce0956dfa794a293089807dbc2131540becb8aa51d24fc7fa3d28df6']`

```text
※ 15시 6분경 클라이언트 패치로 수정되었습니다.
```

Arm Q2 source: `frozen_authored_canary_first_run`.

### 2. 과실복구 신청 경로와 작성할 내용을 알려주고, 내 실수가 복구 대상인지 판정해줘.

- case: `authored_canary_sha256_2da2c7cab1f609754b2910c8e7f168b7f140b0b41a54a503c5e63f9e18fa0995`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 과실복구 신청 경로**

`chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7`

```text
📮 던전앤파이터 과실복구 신청 방법
```

`chunk_sha256_589cbfc58b840f9486846575b938411a778f7a887e3e31bbd9ddfd7a390623d7`

```text
복구 신청 방법을 알려주세요.
```

**R2 · docs=true · 신청 시 작성할 내용**

`chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7`

```text
1:1 문의 작성으로 신청하는 경우 복구가 진행되지 않으니 배너 클릭 후 '과실복구 신청' 통한 문의접수 부탁 드립니다.
```

`chunk_sha256_589cbfc58b840f9486846575b938411a778f7a887e3e31bbd9ddfd7a390623d7`

```text
복구 신청 방법을 알려주세요.
```

**R3 · docs=false · 사용자 실수의 실제 복구 대상 여부**

`chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7`

```text
STEP.1) 과실복구 신청을 위해서는 [복구신청 접수하기] 버튼을 클릭해서 문의해 주셔야 합니다.
```

`chunk_sha256_589cbfc58b840f9486846575b938411a778f7a887e3e31bbd9ddfd7a390623d7`

```text
복구 신청 방법을 알려주세요.
```

`chunk_sha256_506732382b7d997b9eb8520a87056cfe9b27297ed08bc7ba1026e7ce5b1e48b9`

```text
사기는 도용 피해가 아니라 복구 대상에 포함되지 않으며 ,
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7']`

```text
STEP.1) 과실복구 신청을 위해서는 [복구신청 접수하기] 버튼을 클릭해서 문의해 주셔야 합니다.
```

`evidence_2` acceptable chunks: `['chunk_sha256_e74f0944790abf0e7805f69bc1b575ca23e12f0a774eb29abc637329ef0741f7']`

```text
STEP.2) 신속하고 정확한 복구 처리를 위해 요청사항을 명확히 기재해 주시기 바랍니다.
```

Arm Q2 source: `frozen_authored_canary_first_run`.

### 3. 큐브의 계약에서 황금 큐브 효과를 설명하고 내 장비 세팅에 최선인지 골라줘.

- case: `authored_canary_sha256_5edb1f1854d2a8b2d7e71e485e0cc9d0c89bb55a1187c7239b6684c758fe265b`
- first failure: `FALLBACK_EVIDENCE_SELECTION`
- tags: `['ARM_Q_OFFICIAL_EVIDENCE_MISS', 'ARM_Q_EXISTING_CORRECT_MIXED_REGRESSION']`
- labels: Arm0 `correct_mixed_partial` → Arm Q `mixed_missing_evidence` → Arm Q2 `correct_mixed_partial`
- analysis: 안전 partial은 적용됐지만 공식 gold evidence group 인용이 누락됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 황금 큐브의 공식 효과**

`chunk_sha256_6123e12874a8af5ca90eae1ddfac6c02786f81fb8fcfc5c215d33a9ab02788c5`

```text
- 황금 큐브 조각 : 30초 마다 크리티컬 확률 5.5% 증가
```

`chunk_sha256_e5817f79fb2881800fe8f0fba9b08c71b465224cdd9141a8c1cd0d0a2da743c0`

```text
큐브의 계약은 프리미엄 서비스 중 하나로 큐브 조각을 소모하여 무기에 속성을 부여하거나 공격력 증가 등의 버프를 얻을 수 있는 시스템입니다.
```

`chunk_sha256_5dbdcfcae9cea3073a7cf63efb5de573e9a1c5f0a2723f6fc897cefa492002eb`

```text
큐브의 계약은 프리미엄 서비스로 세라 구매 / 골드 구매 / 이벤트 보상 / 그 외 각종 세라 아이템 등을 통해 획득할 수 있습니다.
```

**R2 · docs=false · 사용자 장비 세팅에 최선인지 판단**

No cited span.

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_6123e12874a8af5ca90eae1ddfac6c02786f81fb8fcfc5c215d33a9ab02788c5']`

```text
- 황금 큐브 조각 : 30초 마다 크리티컬 확률 5.5% 증가
```

Arm Q2 source: `frozen_arm0_already_partial`.

### 4. 마일리지샵 시즌7에서 마일리지 소멸 시점과 일일 획득 한도를 알려주고, 내 마일리지가 몇 남을지 계산해줘.

- case: `authored_canary_sha256_9e2c7f69dd204fd5229a8e21b441b7d2c07b3e4ba5eb73ee5b40f5867f4bb875`
- first failure: `QUESTION_PARTIAL_SIGNAL`
- tags: `['ARM_Q_OFFICIAL_EVIDENCE_MISS', 'QUESTION_PARTIAL_SIGNAL_MISS']`
- labels: Arm0 `mixed_missing_evidence` → Arm Q `mixed_missing_evidence` → Arm Q2 `mixed_missing_evidence`
- analysis: 혼합형 질문을 question-level partial 신호가 포착하지 못했다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 마일리지 소멸 시점**

`chunk_sha256_7e1eeb151e0c85131322bfc55a2925bb4916297785f707b61f0f3fe5623642e3`

```text
* 마일리지는 2026년 7월 16일 점검 후부터 적립되며 획득한 마일리지는 시즌이 종료되는 2026년 8월 27일 점검 시 소멸됩니다.
```

`chunk_sha256_b7442aa3725951221e67840ca91ff8da0334d8f5a16888482d889174dec94a8d`

```text
마일리지샵 2026 시즌 7
```

`chunk_sha256_dc49350a5a48df5fc65fe49e3dc80c0c84a9318c666ed533f0b09a9ac6b1c819`

```text
마일리지샵 2026 시즌 7
```

**R2 · docs=true · 일일 마일리지 획득 한도**

`chunk_sha256_7e1eeb151e0c85131322bfc55a2925bb4916297785f707b61f0f3fe5623642e3`

```text
시즌한정
```

`chunk_sha256_b7442aa3725951221e67840ca91ff8da0334d8f5a16888482d889174dec94a8d`

```text
시즌한정
```

`chunk_sha256_dc49350a5a48df5fc65fe49e3dc80c0c84a9318c666ed533f0b09a9ac6b1c819`

```text
별도 안내가 없는 경우,
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_0b5c98314c6c5811af11802b239987441ce3415a8619b74749b883dd4f15ab69']`

```text
- 던전/레이드/결투장을 통해 획득 가능한 마일리지는 일일 최대 50M입니다.
```

`evidence_2` acceptable chunks: `['chunk_sha256_0b5c98314c6c5811af11802b239987441ce3415a8619b74749b883dd4f15ab69']`

```text
- 획득한 마일리지는 시즌이 종료되는 2026년 8월 27일(목) 06시에 소멸됩니다.
```

Arm Q2 source: `arm0_unchanged`.

### 5. 흑아 태초 이관서 획득 방법을 설명하고, 내 악세서리에 쓰는 게 이득인지 정해줘.

- case: `authored_canary_sha256_a3a0c0f5317a0602ffd229d014f3539bee6f559a33e221d457cb202ec816a6fa`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 흑아 태초 이관서 획득 방법**

`chunk_sha256_a9bd9ffc46a1d087fdc08915a7a7850db3a57d08ccbf370d54df45e5a3f2ac88`

```text
'흑아 태초 이관서'는 NPC '신비한 힘의 마법서' 상점에서 판매하는 '흑아 태초 추출서'를 흑아 태초 악세서리에 사용 시 획득할 수 있습니다.
```

`chunk_sha256_e2753eb09e478374883572bc0036100ae6cd161d8f35591dfb39d3117dea665e`

```text
| 흑아 태초 추출서 | 흑아 태초 악세서리를 동일 부위의 태초 악세서리로 변환하고, 흑아 태초 이관서를 획득할 수 있습니다. 획득한 아이템으로 태초 악세서리를 흑아 태초 악세서리로 변환할 수 있습니다. 흑아 태초 악세서리 변환 시 아래의 재료가 필요합니다. - 흑아 태초 변환서 1개 <소모 아이템> * 흑아 태초 악세서리 1개 <결과 아이템> * 태초 악세서리 1개 * 흑아 태초 이관서 1개 강화/증폭/마법부여 옵션이 유지됩니다. | 계정귀속 | 100,000 |
```

`chunk_sha256_16c107f16fd2ef1e38b4923ab2b71a5952a51019a93391fb14700ef86145738c`

```text
| 흑아 태초 변환서 항아리 | 흑아 태초 변환서 중 1종을 균등한 확률로 획득할 수 있습니다. | 계정귀속 |
```

**R2 · docs=false · 사용자 악세서리에 이득인지 판단**

`chunk_sha256_e2753eb09e478374883572bc0036100ae6cd161d8f35591dfb39d3117dea665e`

```text
| 흑아 태초 이관서 | 태초 악세서리를 동일 부위의 흑아 태초 악세서리로 변환할 수 있습니다. <소모 아이템> * 태초 악세서리 1개 * 흑아 태초 변환서 1개 <결과 아이템> * 흑아 태초 악세서리 1개 강화/증폭/마법부여 옵션이 유지됩니다. | 계정귀속 | - |
```

`chunk_sha256_a9bd9ffc46a1d087fdc08915a7a7850db3a57d08ccbf370d54df45e5a3f2ac88`

```text
'흑아 태초 이관서'는 NPC '신비한 힘의 마법서' 상점에서 판매하는 '흑아 태초 추출서'를 흑아 태초 악세서리에 사용 시 획득할 수 있습니다.
```

`chunk_sha256_16c107f16fd2ef1e38b4923ab2b71a5952a51019a93391fb14700ef86145738c`

```text
| 115레벨 세트 태초 악세서리 항아리 선택 상자 | 사용 시 타입 별 태초 악세서리 항아리 중 1종을 선택하여 획득할 수 있습니다. 항아리 개봉 시 태초 소울 3개가 필요합니다. | 계정귀속 |
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_a9bd9ffc46a1d087fdc08915a7a7850db3a57d08ccbf370d54df45e5a3f2ac88']`

```text
'흑아 태초 이관서'는 NPC '신비한 힘의 마법서' 상점에서 판매하는 '흑아 태초 추출서'를 흑아 태초 악세서리에 사용 시 획득할 수 있습니다.
```

Arm Q2 source: `frozen_authored_canary_first_run`.

### 6. 보급 작전 보상 보면 브레이커 키우는 게 내 계정에 제일 좋아?

- case: `retrieval_dev_sha256_144296d937ab23d899b3375c994f2e6568b4a9febb2beb18a68de0a89465c047`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=false · 사용자 계정에서 브레이커 육성이 최선인지 판단**

`chunk_sha256_b82cd64c32226bbf76c6c8e1355cdc7f46ea5382c6d6077ee5761a69a1a67837`

```text
- 썸머 부스트 업 캡슐은 최고 명성 63,257 미만의 전체 대상 캐릭터 1종 / 인파이터(여) 캐릭터 1종 / 브레이커 캐릭터 1종, 총 3번 지정 가능합니다.
```

`chunk_sha256_fa0d7d32cb6a6e4787dd167c86131ab3e9dc7fbbcf323f735937322f1341c8a6`

```text
- 적정 레벨 던전은 15레벨 이상 캐릭터에 적용되는 시스템이며, 적정 레벨 던전은 [채널 선택 > 지역채널] 내 일반 던전 선택창의 던전 썸네일 좌측 하단에 ‘적정레벨’ 표시가 있습니다.
```

`chunk_sha256_cc61e6d054b528513587f608f6c60cf57ca1d8016931787d8d4677b5e0287437`

```text
아포칼립스 3단계 - 필사의 저지를 먼저 클리어한 전직은 브레이커 입니다.
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_fa0d7d32cb6a6e4787dd167c86131ab3e9dc7fbbcf323f735937322f1341c8a6']`

```text
보너스 창고의 보급품은 브레이커 혹은 인파이터(여)만 사용할 수 있습니다. 단, 보너스 보급품은 모든 캐릭터에서 사용 가능합니다.
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.

### 7. 보너스 창고 보급품과 보너스 보급품의 사용 가능 캐릭터를 구분해주고, 브레이커를 키우는 게 좋을지도 정해줘?

- case: `retrieval_dev_sha256_2351c7b115704a5b052bf55b5ca00c74f1851342f17fd98e37a92b1aee851d18`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 두 보급품의 공식 사용 가능 캐릭터**

`chunk_sha256_fa0d7d32cb6a6e4787dd167c86131ab3e9dc7fbbcf323f735937322f1341c8a6`

```text
- 보너스 창고의 보급품은 브레이커 혹은 인파이터(여)만 사용할 수 있습니다.
```

`chunk_sha256_4d868fa672ef45bb61e10fc24d7026282b9ae95da10e5d78fa1d90c21bb401d6`

```text
- 루미나리에 해머
```

`chunk_sha256_faa628327d4fbc2253ff914c5e7cc046f47effcb05c033a4f30c7bf69a2739a6`

```text
(추가) 인파이터(여) - 돈 룩 백 습득 시 할로우 백 스킬 후딜레이를 캔슬하여 다른 스킬을 발동할 수 없는 현상이 수정됩니다.
```

**R2 · docs=false · 사용자가 브레이커를 키우는 것이 좋은지 판단**

`chunk_sha256_fa0d7d32cb6a6e4787dd167c86131ab3e9dc7fbbcf323f735937322f1341c8a6`

```text
- 보너스 창고의 보급품은 브레이커 혹은 인파이터(여)만 사용할 수 있습니다.
```

`chunk_sha256_4d868fa672ef45bb61e10fc24d7026282b9ae95da10e5d78fa1d90c21bb401d6`

```text
브레이커와 인파이터(여) 전용 물약이 피로도 회복 영약 사용창에 표시되지 않는 현상이 수정됩니다.
```

`chunk_sha256_faa628327d4fbc2253ff914c5e7cc046f47effcb05c033a4f30c7bf69a2739a6`

```text
브레이커 - 백병전 전문가 스킬의 적중률 증가 옵션이 정상적으로 적용되지 않는 현상이 수정됩니다.
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_fa0d7d32cb6a6e4787dd167c86131ab3e9dc7fbbcf323f735937322f1341c8a6']`

```text
보너스 창고의 보급품은 브레이커 혹은 인파이터(여)만 사용할 수 있습니다. 단, 보너스 보급품은 모든 캐릭터에서 사용 가능합니다.
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.

### 8. 세라는 현금으로 얼마고 세라샵에서 뭘 살 수 있는지 알려주면서, 내가 지금 충전하는 게 좋을지도 정해줘?

- case: `retrieval_dev_sha256_5d048cff165a5862fcdbdd2784097eeaf10fbe1f4b9facdb99565b67729d7939`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 세라의 공식 현금 가치**

`chunk_sha256_1463d7ac59f3497e4f16e08dba0e32eae7d7e1aecb0c99217dffa2d2415ae6cd`

```text
'세라' 란 던전앤파이터의 게임상 화폐 단위인 골드와 달리 현금으로 충전하는 화폐 단위입니다.(1세라 = 1원)
```

`chunk_sha256_f1917678fa79c7e48c708279c272c9e9f2b1845acab9ec26a3ed6d8d469a5d1e`

```text
세라 충전한도는 한달에 충전할 수 있는 금액 이 정해져 있으며,
```

`chunk_sha256_f1c5a0ba7aeb813cd7a7d9b715547368664389d79c9724e76f6af4469cc9774e`

```text
세라는 던전앤파이터 홈페이지 및 게임 내 세라샵에서 충전할 수 있습니다.
```

**R2 · docs=true · 세라샵의 공식 구매 가능 품목**

`chunk_sha256_1463d7ac59f3497e4f16e08dba0e32eae7d7e1aecb0c99217dffa2d2415ae6cd`

```text
## 세라샵
```

`chunk_sha256_f1c5a0ba7aeb813cd7a7d9b715547368664389d79c9724e76f6af4469cc9774e`

```text
세라는 던전앤파이터 홈페이지 및 게임 내 세라샵에서 충전할 수 있습니다.
```

`chunk_sha256_f1917678fa79c7e48c708279c272c9e9f2b1845acab9ec26a3ed6d8d469a5d1e`

```text
세라 충전한도는 한달에 충전할 수 있는 금액 이 정해져 있으며,
```

**R3 · docs=false · 사용자가 지금 충전하는 것이 좋은지 판단**

`chunk_sha256_f1917678fa79c7e48c708279c272c9e9f2b1845acab9ec26a3ed6d8d469a5d1e`

```text
결제 수단에 따른 충전 가능한 한도는 아래 표와 같습니다.
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_1463d7ac59f3497e4f16e08dba0e32eae7d7e1aecb0c99217dffa2d2415ae6cd']`

```text
'세라' 란 던전앤파이터의 게임상 화폐 단위인 골드와 달리 현금으로 충전하는 화폐 단위입니다.(1세라 = 1원) 세라를 사용하여 세라샵에서 아바타, 코인, 크리쳐 등 다양한 아이템을 구매할 수 있습니다
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.

### 9. 외부에서 결제 재화를 요구받았을 때의 확인·신고 방법을 알려주면서, 내가 받은 연락이 진짜인지도 판단해줘?

- case: `retrieval_dev_sha256_96736fb482a1d58fc401bc329c3d24f93741ffa8d91440338b7fdb7ed59e05de`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 외부 결제 요구의 공식 확인·신고 방법**

`chunk_sha256_da95940aca84c85b8982eaac2d3d989de053117a08480f35044d36b219decc69`

```text
혹시라도 게임 내/외에서 특정 회사의 결제 시스템 관련해 재화를 요구하는 등의 상황이 있다면
```

`chunk_sha256_6b9dc932e194d06fba4869682412425f032ee82b7a09197fa978ee628da351c7`

```text
사기로 습득한 개인정보 및 인증정보가 외부 사이트 결제에 이용되는 경우가 확인되어 모험가님의 각별한 주의가 필요합니다.
```

`chunk_sha256_ef213a7397d6c2225d50ab478d832d51bed8130a7e4cb3d68791b60dbb8447f3`

```text
- 다른 거래방식 제시 및 번복, 별도 결제창 요구
```

**R2 · docs=false · 사용자가 받은 실제 연락의 진위 판단**

`chunk_sha256_ef213a7397d6c2225d50ab478d832d51bed8130a7e4cb3d68791b60dbb8447f3`

```text
별도의 개인대화 또는 외부대화로 접근해오는 경우 주의 필요
```

`chunk_sha256_da95940aca84c85b8982eaac2d3d989de053117a08480f35044d36b219decc69`

```text
해당 기업에서 보낸 내용이 맞는지 진위여부를 공식적인 고객센터로 문의를 하시거나
```

`chunk_sha256_5a70f3d6f9f990fa50180412a3f9cdb3338406dfacd69be6a23fd795a95d2fb2`

```text
[기재 양식]
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_da95940aca84c85b8982eaac2d3d989de053117a08480f35044d36b219decc69']`

```text
혹시라도 게임 내/외에서 특정 회사의 결제 시스템 관련해 재화를 요구하는 등의 상황이 있다면 해당 기업에서 보낸 내용이 맞는지 진위여부를 공식적인 고객센터로 문의를 하시거나 아래의 사이트에서 신고하여 주시기를 부탁드립니다
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.

### 10. 일반 우편과 경매장 구매 우편의 보관 기간을 알려주고, 내가 지금 바로 받아야 하는지도 정해줘?

- case: `retrieval_dev_sha256_a572774c7bbcb8c10ac867faf5071725daaece00c8c43682886d6a1f5b7ffd4a`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 일반 우편 보관 기간**

`chunk_sha256_2ba247d574d6f54e853aaac4b4f11116dd85d5308ada36ac3560d6165196cd0b`

```text
우편 보관 기간은 15일이며, 경매장 구매 아이템은 180일간 보관됩니다.
```

`chunk_sha256_ca2851ccd0d5b29cb18ed7174d610435e5e133580c868df45bdc294a17767c55`

```text
우편의 경우 보낸일로 부터 15일동안 보관되며
```

`chunk_sha256_fcbcd80cfd2f2a2dfa2ff256bda6c1e79f45b28bf3a17f2372e3dd772a4c78ba`

```text
전리품 경매로 발송되는 우편의 보관기간은 15일입니다.
```

**R2 · docs=true · 경매장 구매 우편 보관 기간**

`chunk_sha256_2ba247d574d6f54e853aaac4b4f11116dd85d5308ada36ac3560d6165196cd0b`

```text
우편 보관 기간은 15일이며, 경매장 구매 아이템은 180일간 보관됩니다.
```

`chunk_sha256_fcbcd80cfd2f2a2dfa2ff256bda6c1e79f45b28bf3a17f2372e3dd772a4c78ba`

```text
전리품 경매로 발송되는 우편의 보관기간은 15일입니다.
```

`chunk_sha256_ca2851ccd0d5b29cb18ed7174d610435e5e133580c868df45bdc294a17767c55`

```text
(단, 경매장 구매 /등록 취소 아이템의 경우 6개월간 보관됩니다.)
```

**R3 · docs=false · 사용자가 지금 바로 수령해야 하는지 판단**

`chunk_sha256_ca2851ccd0d5b29cb18ed7174d610435e5e133580c868df45bdc294a17767c55`

```text
또한, 내용을 미처 확인하지 못하고 수령한 우편의 경우
```

`chunk_sha256_2ba247d574d6f54e853aaac4b4f11116dd85d5308ada36ac3560d6165196cd0b`

```text
우편 보관 기간은 15일이며, 경매장 구매 아이템은 180일간 보관됩니다.
```

`chunk_sha256_fcbcd80cfd2f2a2dfa2ff256bda6c1e79f45b28bf3a17f2372e3dd772a4c78ba`

```text
전리품 경매로 발송되는 우편의 보관기간은 15일입니다.
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_2ba247d574d6f54e853aaac4b4f11116dd85d5308ada36ac3560d6165196cd0b']`

```text
우편 보관 기간은 15일이며, 경매장 구매 아이템은 180일간 보관됩니다. 보관 기간이 경과한 우편은 삭제되고 복구할 수 없으니 주의하세요.
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.

### 11. 오라클 탐사 지원의 기초 데이터를 얻을 수 있는 던전을 설명해주면서, 내 캐릭터는 어디를 도는 게 좋을지도 골라줘?

- case: `retrieval_dev_sha256_bad06d84865648fcf4702d7117102cf68d11f24f448dcee9b9ca14c623e90f1d`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT']`
- labels: Arm0 `mixed_overclaim` → Arm Q `correct_mixed_partial` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 기초 데이터 획득 던전**

`chunk_sha256_53e2ad7eb623236ec43257983115ba0c1168afa00986769d34f67ff4ff00867c`

```text
- 기초 데이터는 천해천 지역 적정 레벨 던전과 상급 던전에서만 획득할 수 있습니다.
```

`chunk_sha256_335e912feb7afd35d6f84f0f577b90bb62358201bedde54ff8784877dd910085`

```text
오라클의 천해천 탐사 지원 - 실패 시 랜덤한 비활성화 노드 자동 활성화 옵션의 코어 모듈 효과가 발동할 때, 코어 모듈 효과로 활성화된 노드의 연출이 개선됩니다.
```

`chunk_sha256_8c65b2afd9e9fb7ea02445a8e475c861482bcaffaae0199d0bd44b29b86cf0eb`

```text
오라클의 천해천 탐사 지원 - 카트리지 사용 시 출력되는 UI의 위치를 이동할 수 있는 현상이 수정됩니다.
```

**R2 · docs=false · 사용자 캐릭터에 좋은 던전 추천**

`chunk_sha256_53e2ad7eb623236ec43257983115ba0c1168afa00986769d34f67ff4ff00867c`

```text
* 상급 던전 : 달이 잠긴 호수/애쥬어 메인/죽음의 여신전/해방된 흉몽(챌린지 제외)/별거북 대서고/배교자의 성/최후의 과업
```

`chunk_sha256_8c65b2afd9e9fb7ea02445a8e475c861482bcaffaae0199d0bd44b29b86cf0eb`

```text
- 신궁 루드밀라
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_53e2ad7eb623236ec43257983115ba0c1168afa00986769d34f67ff4ff00867c']`

```text
* 천해천 적정 레벨 던전 : 조율의 경계/최후의 조율자/천해를 품은 하늘 (계시 : 천해를 품은 하늘 던전 포함) * 상급 던전 : 달이 잠긴 호수/애쥬어 메인/죽음의 여신전/해방된 흉몽(챌린지 제외)/별거북 대서고/배교자의 성/최후의 과업 - 시나리오 던전 및 일부 특수 던전에서는 기초 데이터가 드랍되지 않습니다
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.

### 12. 마법부여 상점 설치 방법을 설명해주면서, 수수료와 설치 위치도 내 상황에 맞게 정해줘?

- case: `retrieval_dev_sha256_d946d602ed9908e07789d3782cedf36efa3d45c91631cf785c193268c47475c2`
- first failure: `SEMANTIC_SUPPORT_BOUNDARY`
- tags: `['ARM0_NON_DOC_REQUIREMENT_MARKED_SUPPORTED_EXACT', 'ARM_Q_OFFICIAL_EVIDENCE_MISS']`
- labels: Arm0 `mixed_overclaim` → Arm Q `mixed_missing_evidence` → Arm Q2 `correct_mixed_partial`
- analysis: 사람 라벨상 비문서 요구가 exact span 존재만으로 supported 처리되어 질문에 실제로 답했는지와 원문 일치 여부가 혼동됐다.

#### Requirements and Arm0 exact spans

**R1 · docs=true · 마법부여 상점 설치 방법**

`chunk_sha256_a864fceab10bb6c3d256c85bf3bd0890fbb573d1f516349880a1131bf1a34361`

```text
## 마법부여 상점 설치
```

`chunk_sha256_233ac3fb9ea8453bfe0c873ad6e4d2bc8e5359a6282f6e3b7d4555d474363eb6`

```text
### 마법부여 상점이 설치된 모습
```

`chunk_sha256_5715b4b56c536d976f605b46f02201496d583a86bbbfffcf537088a5bcb4b768`

```text
재료를 모두 소지한 상태에서 카드와 장비를 등록하면 마법부여를 진행할 수 있으며, 부여하는 카드의 등급에 따라 다음의 재료가 소모됩니다.
```

**R2 · docs=false · 사용자 상황에 맞는 수수료 결정**

`chunk_sha256_a864fceab10bb6c3d256c85bf3bd0890fbb573d1f516349880a1131bf1a34361`

```text
마법부여 상점을 설치하여 다른 모험가로부터 수수료를 받아 수입을 올리거나 숙련도를 상승시킬 수 있습니다.
```

`chunk_sha256_5715b4b56c536d976f605b46f02201496d583a86bbbfffcf537088a5bcb4b768`

```text
재료 외에 수수료를 지급하고 다른 모험가의 마법부여 상점을 이용할 수 있습니다.
```

`chunk_sha256_233ac3fb9ea8453bfe0c873ad6e4d2bc8e5359a6282f6e3b7d4555d474363eb6`

```text
### 수수료 입력
```

**R3 · docs=false · 사용자 상황에 맞는 설치 위치 결정**

`chunk_sha256_a864fceab10bb6c3d256c85bf3bd0890fbb573d1f516349880a1131bf1a34361`

```text
## 마법부여 상점 설치
```

`chunk_sha256_233ac3fb9ea8453bfe0c873ad6e4d2bc8e5359a6282f6e3b7d4555d474363eb6`

```text
### 마법부여 상점이 설치된 모습
```

`chunk_sha256_5715b4b56c536d976f605b46f02201496d583a86bbbfffcf537088a5bcb4b768`

```text
재료 외에 수수료를 지급하고 다른 모험가의 마법부여 상점을 이용할 수 있습니다.
```

#### Human gold evidence

`evidence_1` acceptable chunks: `['chunk_sha256_a864fceab10bb6c3d256c85bf3bd0890fbb573d1f516349880a1131bf1a34361']`

```text
전문직업(J) → 상점 설치 클릭 → 수수료 입력 → 원하는 위치를 선택하면 마법부여 상점이 설치됩니다
```

Arm Q2 source: `frozen_canonical_claim_reranker_v3_1`.
