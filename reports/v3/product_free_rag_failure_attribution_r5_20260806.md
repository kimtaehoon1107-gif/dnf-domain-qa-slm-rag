# Product Free RAG A6 실패 단계별 귀속 재도출 (R5)

작성일: 2026-08-06

성격: 저장 산출물 재분석 전용, Qwen 호출 0회, 런타임 변경 없음

원시 결과: `product_free_rag_failure_attribution_r5_20260806.jsonl`

## 결론

공식 사람 판정 실패 13문항에 포함된 **지원 요구는 21개**지만, 그 21개가 모두 실패한 것은 아니었다. 요구 단위로 다시 대조하면 실제 실패한 지원 요구는 14개이고, 나머지 7개는 같은 문항의 다른 요구 때문에 실패 문항에 묶였을 뿐 pack·claim·노출이 정상이다.

따라서 21개를 모두 S1~S5에 강제로 넣지 않았다. 지시서가 허용한 `S?`에 **“해당 요구 자체는 실패하지 않음”** 7개를 보존했다. 이 구분 없이 21개를 모두 실패로 보고하면 slot 26의 정상 `purchase_reward` 같은 요구에 존재하지 않는 실패 단계를 만들어내게 된다.

실제 실패 14개 중 가장 큰 구간은 **S2 evidence pack 선택 5개(35.7%)**다. 다음은 S4 verifier rejection 4개, S3 생성 3개, S1 검색 1개, S5 의미·관계 오연결 1개다.

## 귀속 표

### 지시서 계약인 21개 전체

| 단계 | 요구 수 | 21개 대비 | 대표 사례 |
|---|---:|---:|---|
| S1 검색 | 1 | 4.8% | slot 22 고객센터 gold가 최종 후보에 없음 |
| S2 pack 선택 | 5 | 23.8% | slot 1 한도 일부, slot 26의 9,800 세라 없음 |
| S3 생성 | 3 | 14.3% | slot 11 판매 종료일 누락 |
| S4 verifier rejection | 4 | 19.0% | slot 10 두 요구, slot 28, slot 32 |
| S5 의미·관계 오연결 | 1 | 4.8% | slot 7의 12→9초를 잘못된 대상에 결합 |
| S? 해당 요구는 정상 | 7 | 33.3% | slot 26 구매 보상 등 |
| **합계** | **21** | **100%** | 공식 실패 13문항의 지원 요구 전부 |

### 실제 실패한 지원 요구 14개만 본 분포

| 단계 | 요구 수 | 14개 대비 |
|---|---:|---:|
| S1 검색 | 1 | 7.1% |
| S2 pack 선택 | 5 | 35.7% |
| S3 생성 | 3 | 21.4% |
| S4 verifier rejection | 4 | 28.6% |
| S5 의미·관계 오연결 | 1 | 7.1% |
| **합계** | **14** | **100%** |

S4 네 건을 모두 “verifier 과차단”이라고 부르면 부정확하다. slot 10의 두 claim과 slot 28은 정답 과차단이지만, slot 32는 지원값 `+221`과 비지원값 `구매 제한 1개`를 묶은 raw claim을 안전하게 차단한 사례다. 규칙상 첫 손실 지점은 S4지만 근본 원인은 claim 결합이다.

## 요구별 상세 21건

| slot | 요구 | 정답값 | 값 유형 | 단계 | 사람이 재확인할 근거 |
|---:|---|---|---|:---:|---|
| 1 | transfer_limits | 1회 50만원 / 1일 200만원 / 1월 500만원 / 1일 횟수 제한 없음 | 수치·화폐 | S2 | M3 partial. pack에는 1일 200만원·횟수 제한 없음만 있고 1회 50만원·1월 500만원이 없다. |
| 2 | maintenance_start | 8월 12일 15시 | 날짜·시각 | S3 | pack에는 15시가 있으나 Qwen은 14시를 노출했고 15시는 claim하지 않았다. |
| 2 | reopen_date | 8월 13일(수) | 날짜 | S? | pack과 노출 claim 모두 8월 13일 재오픈을 담았다. 이 요구는 정상이다. |
| 4 | privacy_request_penalty | 영구 게임 이용 제한 | 서술형 | S? | pack과 노출 답변에 영구 게임 이용 제한이 모두 있다. 이 요구는 정상이다. |
| 4 | report_path | 캐릭터 이름 클릭 / 신고하기 / 거래 사기 등록 | 서술형 절차 | S2 | M3 none. 세 단계 신고 경로가 pack에 없다. |
| 6 | primal_will_shop_terms | 광휘의 잔영 790개 / 계정당 1회 | 수치 | S? | 두 값이 pack과 노출 답변에 모두 있다. 당시 문항 실패는 별도 unsupported 요구 때문이었다. |
| 7 | base_cooldown_change | 20초 / 18초 | 시간 | S2 | overlap 문장은 “쿨타임이 감소합니다”까지만 담고 20초·18초는 둘 다 없다. |
| 7 | gale_option_cooldown_change | 12초 / 9초 | 시간 | S5 | pack과 승인 claim에 두 값이 있으나 Qwen이 질풍 개화가 아닌 타이드 바운드 값으로 노출했다. |
| 10 | daily_clear_requirement | 10회 | 수치 | S4 | pack에 10회가 있고 Qwen도 생성했으나 verifier가 `factual_values_not_in_evidence`로 제거했다. |
| 10 | daily_fishing_limit | 계정당 1회 / 매일 오전 06시 초기화 | 수치·시각 | S4 | 두 값이 pack과 raw claim에 있으나 같은 reason으로 제거됐다. |
| 11 | deletion_at | 2026-09-04 06시 | 날짜·시각 | S? | pack과 노출 claim 모두 정확하다. 이 요구는 정상이다. |
| 11 | purchase_reset | 매주 목요일 06시 | 반복·시각 | S? | pack과 노출 claim 모두 정확하다. 이 요구는 정상이다. |
| 11 | sales_period | 2026-06-04 점검 후 / 2026-08-27 점검 전 | 날짜 범위 | S3 | pack에는 양 끝이 있지만 Qwen은 시작일만 답하고 8월 27일 종료를 누락했다. |
| 13 | mypin_properties | 13자리 / 유효기간 3년 / 연 5회 재발급 | 수치·기간 | S2 | M3 partial. 13자리·3년은 있으나 연 5회가 pack에 없어서 이후 verifier 전에 이미 손실됐다. |
| 14 | available_views | 등록한 아이템 현황 / 다른 모험가가 등록한 아이템 검색 | 서술형 목록 | S3 | pack에는 두 정보가 모두 있지만 Qwen은 둘 중 어느 것도 claim하지 않았다. |
| 14 | mobile_trading | 직접 구매·판매 불가 | 서술형 boolean | S? | 직접 거래 불가를 지원하고 노출했다. 반복 표현 문제는 있지만 이 요구는 정상이다. |
| 22 | bug_reporting_channel | 고객센터 | 서술형 | S1 | gold는 hybrid 28위이고 최종 후보 8개에 없어 pack 단계에 도달하지 못했다. |
| 26 | contract_price_duration | 9,800 세라 / 30일 | 화폐·기간 | S2 | M3 partial. 30일은 있으나 9,800 세라가 pack에 없다. |
| 26 | purchase_reward | 해방의 열쇠 10개 상자 1개 | 서술형 | S? | pack과 노출 답변에 정확히 있다. 이 요구는 정상이다. |
| 28 | tropical_hat_box | 프리미엄 코인 2개 / 계정당 5회 / 2026-08-27 06시 | 수치·날짜·시각 | S4 | 계정당 5회가 pack과 raw claim에 있으나 `cross_parent_structured_value_conflict`로 제거됐다. |
| 32 | october_siv_fame | +221 | 수치 | S4 | pack과 raw claim에 +221이 있으나 unsupported 구매 제한 1개와 한 claim으로 묶여 전체 제거됐다. |

## W6 대비 변경

W6 v2는 overlap 기반으로 5문항·8요구만 분류했다. R5는 value presence와 저장 claim/rejected claim을 사용해 공식 실패 문항의 지원 요구 21개 전부를 다시 보았다.

| 대상 | W6/기존 판정 | R5 | 변경 이유 |
|---|---|---|---|
| A6-1 transfer_limits | claim generation / relation binding | **S2** | overlap은 있었지만 필수값 4개 중 2개만 pack에 있었다. |
| A6-7 base_cooldown_change | claim generation / relation binding | **S2** | 겹친 문장에 20초와 18초가 모두 없었다. |
| A6-7 gale_option_cooldown_change | visible and cited | **S5** | 값과 인용은 있으나 12→9초를 타이드 바운드에 잘못 결합했다. |
| A6-26 contract_price_duration | 사람 판정상 생성 누락 | **S2** | Qwen 전에 pack에서 9,800 세라가 이미 빠져 있었다. |

의미상 유지된 항목도 명시한다.

- A6-2 `maintenance_start`: W6의 claim-generation 계열 → R5 S3
- A6-4 `report_path`: W6 evidence-pack selection → R5 S2
- A6-22 `bug_reporting_channel`: W6 initial retrieval pool → R5 S1
- W6의 `visible_and_cited` 중 A6-2 `reopen_date`, A6-4 `privacy_request_penalty`는 실패가 아니라 정상 요구이므로 S?로 보존

## 값 유형 분리

### numeric · date · time · currency 계열 15개

| M3 value presence | 요구 수 |
|---|---:|
| full | 11 |
| partial | 3 |
| none | 1 |
| 합계 | 15 |

이 계열의 S2 판정은 실제 필수 숫자·날짜·시각·통화값 존재 여부를 사용했다. A6-1, A6-13, A6-26은 partial이고 A6-7 본체는 none이다. 단순 좌표 overlap은 판정 근거로 쓰지 않았다.

### descriptive 계열 6개

| M3 value presence | 요구 수 |
|---|---:|
| full | 3 |
| none | 2 |
| boolean 별도 | 1 |
| 합계 | 6 |

서술형은 M3 문자열 판정을 단독 사용하지 않았다. 전체 A6에서 A6-17의 역할 결합 표현과 A6-29의 다열 표처럼, 값은 맞아도 subject/column 문맥이 분리되어 M3가 partial·none으로 보는 위양성이 이미 확인됐기 때문이다. R5의 서술형 판정은 pack 원문과 공식 사람 판정, 노출 claim을 함께 대조했다.

## unsupported 사건은 21개 밖에 별도 보존

지원 요구 21개만으로는 실패 문항의 모든 안전 사건을 설명할 수 없다.

| slot | unsupported 요구 | 사건 |
|---:|---|---|
| 6 | primal_oath_exact_probability | 공식 19/32 레이어에서는 false-full. 별도 slot 6 재판정 커밋에서 처리한다. |
| 22 | bug_report_response_deadline | 문서에 없는 답변 기한을 12/4(목)로 노출한 human overclaim이다. 지원 요구의 1차 귀속 S1과 별개다. |
| 32 | october_siv_account_limit | 비지원 구매 제한을 +221과 묶어 raw claim을 만들었고 전체 claim 제거를 유발했다. |

따라서 지시서가 S5 대표로 든 A6-1·A6-22는 다음처럼 해석해야 한다.

- A6-1에는 네이버페이 대상 오연결도 있었지만, first-failure 규칙상 그보다 앞선 pack 값 손실이 있어 S2다.
- A6-22의 지원 요구 `고객센터`는 S1이다. `12/4` 오연결은 21개 밖의 unsupported 요구에 대한 별도 안전 사건이다.
- first-failure S5로 남는 지원 요구는 A6-7 `gale_option_cooldown_change` 한 건이다.

## 공통 무결성

- 공식 사람 판정 기준: 19/32, 실패 문항 13개
- 지원 요구 합계: 21개
- Qwen 호출: 0회
- evidence pack 재구성: 없음
- frozen set 수정: 없음
- 런타임 변경: 없음
- 미적용 랭킹 결합·예약 fallback·coverage 계약 활성화: 없음
- R5 이후 추가 진단·수정 라운드: 제안하지 않음

## 회귀

- R5 전용 테스트: **3 passed**
- 전체 `tests/v3`: **1254 passed, 67 subtests passed**
- 실패: 지시서에 명시된 기존 manifest SHA 면제 2건
  - `test_retrieve_decomposed::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings`
  - `test_run_unified_runtime::test_full_replay_is_content_addressed_and_reproducible`
- R5로 생긴 새 회귀: **0건**
