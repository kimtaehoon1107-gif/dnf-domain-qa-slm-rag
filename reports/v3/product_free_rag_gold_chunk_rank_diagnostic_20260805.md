# Product Free RAG 골드 청크 순위 진단

작성일: 2026-08-05

성격: 진단 전용, 런타임 변경 없음, Qwen 호출 0회

원시 결과: `product_free_rag_gold_chunk_rank_diagnostic_20260805.jsonl`

## 결론

**A6 실패의 주원인은 검색 깊이가 아니다.** 공식 사람 판정 실패 13건의 지원 요구 21개 중 19개(90.5%)는 골드가 이미 현행 hybrid top 20에 있었고, 20개(95.2%)는 최종 후보 8개에 있었다. 검색 깊이 때문에 최종 후보에서 빠진 요구는 slot 22의 `bug_reporting_channel` 한 건뿐이다.

사전 등록한 세 갈래 중 전역 판정은 `depth_not_primary_downstream_loss`다. 실패 요구의 압도적 다수가 1~20위이므로 A·B·C 중 어느 검색 처방도 A6 전체의 주 처방이 아니다. 남은 실패는 evidence pack, 생성, 검증 같은 검색 이후 단계를 요구별로 분석해야 한다.

다만 **slot 22만 따로 보면 A안 조건**에 해당한다. 골드는 BM25 74위, dense 33위, hybrid 28위여서 측정용 top 200에는 있으나 현행 top 20에는 없다. 이 한 건을 근거로 전역 깊이는 바꾸지 않으며, 이번 라운드에서는 처방도 구현하지 않았다.

## 측정 조건과 판정 기준

- 대상: 동결 A6 32문항, 지원 요구 57개, unsupported/no-gold 요구 4개
- 검색: 현행 BM25·BGE-M3 조건으로 각각 top 200까지 진단용 확장
- 현행 후보 조립: 현재 hybrid top 20, identity shortlist, BGE reranker, 최종 8개
- source 진입률 차이 20%p 이상을 `뚜렷함`으로 사전 등록
- Spearman 절댓값 0.30 이상을 `뚜렷한 상관`으로 사전 등록
- 실패 요구의 hybrid 순위 구간 중 최다 구간으로 주 판정
- Qwen 호출: 0회
- 런타임 코드·기본 검색 깊이·코퍼스·인덱스 변경: 없음

### A6 성공 수 불일치 처리

진단 지시서에는 성공 20건·실패 12건으로 적혀 있으나, 잠긴 공식 사람 판정 문서 `product_free_rag_a6_final_adjudication.md`는 성공 19건·실패 13건이다. 재해석하지 않고 공식 판정의 슬롯 집합을 사용했다.

- 성공: 3, 5, 8, 9, 12, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 27, 29, 30, 31
- 실패: 1, 2, 4, 6, 7, 10, 11, 13, 14, 22, 26, 28, 32

## D1. 골드 청크 순위

| 그룹 | 문항 | 지원 요구 | BM25 중앙값 | Dense 중앙값 | Hybrid 중앙값 | Hybrid 1~20 | 21~40 | 41~200 | null | 현행 top20 진입 | 최종8 진입 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 성공 | 19 | 36 | 1 | 1 | 1 | 34 | 0 | 0 | 2 | 34/36 (94.4%) | 36/36 (100%) |
| 실패 | 13 | 21 | 1.5 | 1 | 1 | 19 | 1 | 0 | 1 | 19/21 (90.5%) | 20/21 (95.2%) |
| 전체 | 32 | 57 | 1 | 1 | 1 | 53 | 1 | 0 | 3 | 53/57 (93.0%) | 56/57 (98.2%) |

### 문항 × 요구 전체 표

`—`는 top 200에도 없음을 뜻한다. `현행 top20`은 실제 런타임 깊이 안에 골드가 있었는지, `최종8`은 identity 후보 조립과 reranker 이후 남았는지를 뜻한다.

| slot | 결과 | 요구 | 출처 | BM25 | Dense | Hybrid | 현행 top20 | Rerank | 최종8 |
|---:|---|---|---|---:|---:|---:|:---:|---:|:---:|
| 1 | failure | transfer_limits | dnf_notice | 1 | 1 | 1 | Y | 1 | Y |
| 2 | failure | maintenance_start | dnf_notice | 1 | 1 | 1 | Y | 1 | Y |
| 2 | failure | reopen_date | dnf_notice | 1 | 1 | 1 | Y | 1 | Y |
| 3 | success | orb_auction_period | dnf_notice | 2 | 1 | 1 | Y | 1 | Y |
| 3 | success | auction_appearance_rate | dnf_notice | 1 | 2 | 2 | Y | 2 | Y |
| 4 | failure | report_path | dnf_notice | 6 | 2 | 1 | Y | 1 | Y |
| 4 | failure | privacy_request_penalty | dnf_notice | 6 | 2 | 1 | Y | 1 | Y |
| 5 | success | channel_added | dnf_update | 3 | 1 | 1 | Y | 1 | Y |
| 5 | success | play_available_at | dnf_update | 3 | 1 | 1 | Y | 1 | Y |
| 6 | failure | primal_will_shop_terms | dnf_update | 1 | 1 | 1 | Y | 1 | Y |
| 7 | failure | base_cooldown_change | dnf_update | 1 | 1 | 1 | Y | 1 | Y |
| 7 | failure | gale_option_cooldown_change | dnf_update | 1 | 1 | 1 | Y | 1 | Y |
| 8 | success | countdown_duration | dnf_update | 2 | 4 | 4 | Y | 2 | Y |
| 8 | success | gauge_recovery | dnf_update | 2 | 4 | 4 | Y | 2 | Y |
| 9 | success | pvp_mileage | dnf_event | 1 | 1 | 1 | Y | 1 | Y |
| 9 | success | gift_mileage | dnf_event | 1 | 1 | 1 | Y | 1 | Y |
| 10 | failure | daily_clear_requirement | dnf_event | 2 | 1 | 1 | Y | 1 | Y |
| 10 | failure | daily_fishing_limit | dnf_event | 2 | 1 | 1 | Y | 1 | Y |
| 11 | failure | sales_period | dnf_event | 1 | 1 | 1 | Y | 1 | Y |
| 11 | failure | purchase_reset | dnf_event | 1 | 1 | 1 | Y | 1 | Y |
| 11 | failure | deletion_at | dnf_event | 1 | 1 | 1 | Y | 1 | Y |
| 12 | success | time_accumulation | dnf_event | 1 | 2 | 1 | Y | 2 | Y |
| 12 | success | daily_reset | dnf_event | 1 | 2 | 1 | Y | 2 | Y |
| 13 | failure | mypin_properties | dnf_faq | 4 | 1 | 1 | Y | 1 | Y |
| 14 | failure | mobile_trading | dnf_faq | — | 1 | 1 | Y | 1 | Y |
| 14 | failure | available_views | dnf_faq | — | 1 | 1 | Y | 1 | Y |
| 15 | success | setup_path | dnf_faq | 3 | 2 | 3 | Y | 1 | Y |
| 15 | success | password_length | dnf_faq | 3 | 2 | 3 | Y | 1 | Y |
| 16 | success | reissue_location | dnf_faq | 2 | 1 | 1 | Y | 1 | Y |
| 16 | success | in_app_reissue | dnf_faq | 2 | 1 | 1 | Y | 1 | Y |
| 17 | success | required_materials | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 17 | success | material_consumption | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 17 | success | mold_trade_types | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 18 | success | appearance_condition | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 18 | success | excluded_dungeons | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 18 | success | contract_effects | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 19 | success | party_speaking_rights | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 19 | success | raid_speaking_rights | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 20 | success | inventory_key | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 20 | success | soul_cube_storage | dnf_game_guide | 1 | 1 | 1 | Y | 1 | Y |
| 21 | success | account_theft_recovery_request_period | dnf_account_policy | 4 | 3 | 2 | Y | 1 | Y |
| 21 | success | account_theft_recovery_after_deadline | dnf_account_policy | 4 | 3 | 2 | Y | 1 | Y |
| 22 | failure | bug_reporting_channel | dnf_account_policy | 74 | 33 | 28 | N | — | N |
| 23 | success | same_identity_permanent_restriction | dnf_account_policy | 1 | 3 | 2 | Y | 1 | Y |
| 24 | success | minor_deletion_request | dnf_account_policy | 1 | 2 | 1 | Y | 1 | Y |
| 24 | success | minor_hidden_without_notice | dnf_account_policy | 1 | 2 | 1 | Y | 1 | Y |
| 25 | success | normal_mold | dnf_seria_shop | 4 | 2 | 2 | Y | 2 | Y |
| 25 | success | steel_mold | dnf_seria_shop | 3 | 1 | 1 | Y | 1 | Y |
| 26 | failure | contract_price_duration | dnf_seria_shop | 10 | 2 | 2 | Y | 1 | Y |
| 26 | failure | purchase_reward | dnf_seria_shop | 10 | 2 | 2 | Y | 1 | Y |
| 27 | success | vault2_unlock | dnf_seria_shop | 1 | 3 | 3 | Y | 1 | Y |
| 27 | success | vault2_stage16 | dnf_seria_shop | 1 | 3 | 3 | Y | 1 | Y |
| 28 | failure | tropical_hat_box | dnf_seria_shop | 3 | 5 | 3 | Y | 1 | Y |
| 29 | success | august_special_box_prices | dnf_monthly_item | — | — | — | N | 1 | Y |
| 30 | success | july_box_contents | dnf_monthly_item | 2 | 1 | 1 | Y | 2 | Y |
| 31 | success | grand_master_contract_contents | dnf_monthly_item | — | — | — | N | 1 | Y |
| 32 | failure | october_siv_fame | dnf_monthly_item | — | — | — | N | 1 | Y |

### Top 200에도 없는 골드

| slot | 결과 | 요구 | 출처 | 최종8 |
|---:|---|---|---|:---:|
| 29 | success | august_special_box_prices | dnf_monthly_item | Y |
| 31 | success | grand_master_contract_contents | dnf_monthly_item | Y |
| 32 | failure | october_siv_fame | dnf_monthly_item | Y |

세 요구 모두 BM25와 dense top 200에는 없지만, 문서 identity shortlist가 골드 문서를 주입하여 reranker 1위·최종 후보 진입을 복구했다. 따라서 이 세 건을 곧바로 C안의 근거로 볼 수 없다. 특히 slot 32는 골드가 최종 후보에 있으므로 검색 후단 실패다.

## D2. 출처별 집계

| source_id | 문항 | 요구 | 현행 top20 진입률 | 최종8 진입률 | Hybrid 중앙값 | top200 null |
|---|---:|---:|---:|---:|---:|---:|
| dnf_account_policy | 4 | 6 | 83.3% | 83.3% | 2 | 0 |
| dnf_event | 4 | 9 | 100% | 100% | 1 | 0 |
| dnf_faq | 4 | 7 | 100% | 100% | 1 | 0 |
| dnf_game_guide | 4 | 10 | 100% | 100% | 1 | 0 |
| dnf_monthly_item | 4 | 4 | 25.0% | 100% | 1 | 3 |
| dnf_notice | 4 | 7 | 100% | 100% | 1 | 0 |
| dnf_seria_shop | 4 | 7 | 100% | 100% | 2 | 0 |
| dnf_update | 4 | 7 | 100% | 100% | 1 | 0 |

`dnf_account_policy`와 나머지의 현행 top20 진입률 차이는 10.8%p(83.3% 대 94.1%), 최종8 차이는 16.7%p(83.3% 대 100%)다. 둘 다 사전 등록한 20%p 기준에 못 미치므로 **정책 계열 전체의 구조 문제라고 판정하지 않는다.** 표본 내에서는 slot 22의 개별 사례다.

`dnf_monthly_item`의 일반 검색 진입률 25%는 낮지만, 현재 identity shortlist가 4/4를 모두 최종 후보에 복구한다. 이 진단에서 월간 상품 계열의 런타임 최종 coverage 문제는 관찰되지 않았다.

## D3. 청크 크기와 신호 비율

- 관측 골드 unit: 62개
- top 200 밖 순위는 상관 계산에서 201로 검열
- 청크 길이 대 hybrid 순위 Spearman rho: **0.2025**
- 신호 비율 대 hybrid 순위 Spearman rho: **-0.2801**

두 값 모두 사전 기준 `|rho| >= 0.30`에 못 미친다. 즉 **청크가 길거나 정답 문장 비율이 작을수록 전반적으로 순위가 나빠진다는 가설은 이 A6 표본에서 입증되지 않았다.**

| 청크 길이 사분위 | 범위(자) | 관측 | Hybrid 중앙값 | null |
|---|---:|---:|---:|---:|
| Q1 | 106–437 | 15 | 1 | 0 |
| Q2 | 460–670 | 16 | 1 | 0 |
| Q3 | 681–1,210 | 15 | 1 | 3 |
| Q4 | 1,226–1,765 | 16 | 1 | 0 |

| 신호 비율 사분위 | 범위 | 관측 | Hybrid 중앙값 | null |
|---|---:|---:|---:|---:|
| Q1 | 1.29–3.18% | 15 | 1 | 2 |
| Q2 | 3.47–5.53% | 16 | 1 | 1 |
| Q3 | 5.59–11.30% | 15 | 1 | 0 |
| Q4 | 11.86–48.44% | 16 | 1 | 0 |

### 정책 청크 내부 대조

| slot | 요구 | 청크 길이 | evidence 길이 | 신호 비율 | Hybrid | 최종8 |
|---:|---|---:|---:|---:|---:|:---:|
| 21 | account_theft_recovery_request_period | 1,765 | 55 | 3.12% | 2 | Y |
| 21 | account_theft_recovery_after_deadline | 1,765 | 47 | 2.66% | 2 | Y |
| 22 | bug_reporting_channel | 1,703 | 34 | 2.00% | 28 | N |
| 23 | same_identity_permanent_restriction | 1,606 | 87 | 5.42% | 2 | Y |
| 24 | minor_deletion_request | 1,663 | 77 | 4.63% | 1 | Y |
| 24 | minor_hidden_without_notice | 1,663 | 93 | 5.59% | 1 | Y |

slot 22와 비슷하게 길고 신호 비율이 낮은 정책 청크도 1~2위에 든다. slot 22의 원인은 정책 청크 크기 자체보다, 질문에 정확히 겹치는 제목을 가진 공지·FAQ가 다수 경쟁한 개별 어휘·제목 신호 문제로 보는 것이 데이터에 맞다.

## D4. 최종 후보 출처 분포

| slot | 결과 | 골드 출처 | 최종 후보 출처 분포 | 골드 출처 부재 |
|---:|---|---|---|---:|
| 1 | failure | dnf_notice | dnf_faq 3; dnf_notice 5 | N |
| 2 | failure | dnf_notice | dnf_notice 7; dnf_update 1 | N |
| 3 | success | dnf_notice | dnf_notice 5; dnf_game_guide 3 | N |
| 4 | failure | dnf_notice | dnf_event 1; dnf_faq 1; dnf_notice 4; dnf_account_policy 2 | N |
| 5 | success | dnf_update | dnf_game_guide 3; dnf_update 2; dnf_notice 1; dnf_seria_shop 2 | N |
| 6 | failure | dnf_update | dnf_update 3; dnf_game_guide 5 | N |
| 7 | failure | dnf_update | dnf_notice 2; dnf_update 5; dnf_event 1 | N |
| 8 | success | dnf_update | dnf_update 5; dnf_game_guide 3 | N |
| 9 | success | dnf_event | dnf_seria_shop 4; dnf_event 1; dnf_notice 1; dnf_faq 2 | N |
| 10 | failure | dnf_event | dnf_seria_shop 5; dnf_event 2; dnf_game_guide 1 | N |
| 11 | failure | dnf_event | dnf_event 2; dnf_seria_shop 3; dnf_notice 3 | N |
| 12 | success | dnf_event | dnf_update 2; dnf_game_guide 3; dnf_event 2; dnf_notice 1 | N |
| 13 | failure | dnf_faq | dnf_faq 8 | N |
| 14 | failure | dnf_faq | dnf_faq 2; dnf_update 2; dnf_game_guide 3; dnf_notice 1 | N |
| 15 | success | dnf_faq | dnf_faq 8 | N |
| 16 | success | dnf_faq | dnf_faq 8 | N |
| 17 | success | dnf_game_guide | dnf_faq 2; dnf_game_guide 3; dnf_seria_shop 3 | N |
| 18 | success | dnf_game_guide | dnf_faq 1; dnf_game_guide 3; dnf_seria_shop 2; dnf_event 1; dnf_update 1 | N |
| 19 | success | dnf_game_guide | dnf_faq 1; dnf_game_guide 7 | N |
| 20 | success | dnf_game_guide | dnf_faq 4; dnf_game_guide 4 | N |
| 21 | success | dnf_account_policy | dnf_faq 6; dnf_account_policy 2 | N |
| 22 | failure | dnf_account_policy | dnf_notice 7; dnf_faq 1 | **Y** |
| 23 | success | dnf_account_policy | dnf_faq 5; dnf_account_policy 2; dnf_notice 1 | N |
| 24 | success | dnf_account_policy | dnf_notice 5; dnf_faq 1; dnf_account_policy 2 | N |
| 25 | success | dnf_seria_shop | dnf_seria_shop 4; dnf_faq 1; dnf_game_guide 3 | N |
| 26 | failure | dnf_seria_shop | dnf_monthly_item 1; dnf_faq 1; dnf_seria_shop 5; dnf_game_guide 1 | N |
| 27 | success | dnf_seria_shop | dnf_faq 2; dnf_seria_shop 5; dnf_event 1 | N |
| 28 | failure | dnf_seria_shop | dnf_event 3; dnf_seria_shop 5 | N |
| 29 | success | dnf_monthly_item | dnf_monthly_item 2; dnf_notice 1; dnf_seria_shop 5 | N |
| 30 | success | dnf_monthly_item | dnf_seria_shop 4; dnf_event 3; dnf_monthly_item 1 | N |
| 31 | success | dnf_monthly_item | dnf_monthly_item 1; dnf_notice 1; dnf_seria_shop 6 | N |
| 32 | failure | dnf_monthly_item | dnf_monthly_item 2; dnf_notice 1; dnf_game_guide 2; dnf_seria_shop 3 | N |

골드 출처가 최종 후보에 하나도 없는 문항은 **slot 22 한 건(1/32)**뿐이다. 사전 등록한 B안 조건은 “여러 문항”이므로 출처 다양성 보장 실험의 전역 근거는 충족되지 않았다.

## 최종 판정

| 판정 항목 | 결과 | 근거 |
|---|---|---|
| 주 판정 | **검색 깊이가 주원인 아님** | 실패 지원 요구 21개 중 19개가 1~20위, 20개가 최종8 진입 |
| A안 | 전역 NO, slot 22만 후보 | slot 22 hybrid 28위 |
| B안 | NO | 골드 출처 부재가 1/32뿐 |
| C안 | NO | null 3건은 identity가 전부 복구; 청크 크기 상관도 기준 미달 |
| 정책 계열 문제 | NO | 다른 출처 대비 진입률 격차 최대 16.7%p < 20%p |
| 청크 크기 문제 | NO | rho 0.2025, 신호 비율 rho -0.2801 |

이 결과는 slot 22의 국소 검색 실패를 부정하지 않는다. 다만 A6 전체 실패를 “골드가 검색되지 않아서”로 설명할 수 없다는 뜻이다. 다음 분석 단위는 실패 슬롯별 `최종 후보 → evidence pack → Qwen claim → verifier` 후단 waterfall이어야 한다. 지시서에 따라 이번 라운드에서는 그 수정이나 A/B를 실행하지 않았다.

## 회귀

- 진단 전용 테스트: **3 passed**
- 전체 `tests/v3`: **1251 passed, 67 subtests passed**
- 실패: **2건** — 지시서에 명시된 기존 manifest SHA 면제 항목과 정확히 일치
  - `test_retrieve_decomposed::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings`
  - `test_run_unified_runtime::test_full_replay_is_content_addressed_and_reproducible`
- 이번 진단으로 생긴 새 회귀: **0건**
