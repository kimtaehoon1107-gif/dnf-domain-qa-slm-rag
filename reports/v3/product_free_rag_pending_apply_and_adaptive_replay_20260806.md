# ADAPTIVE 진단 — Product Free RAG 미결정 2건 적용과 A6 재측정

**ADAPTIVE 진단 결과이며 blind·공식 A6 성능이 아니다. 공식 sealed one-shot은 20/32(62.5%)로 유지한다.**

작성일: 2026-08-06

대상: `product_free_rag_v1` + A1 랭킹 문맥 결합 + A2 요구사항 예약 fallback

결론: **NO-GO** — adaptive 수동 의미 판정은 24/32(75%)로 80%에 못 미쳤고, 공식 정답 slot 25가 1건 악화됐다.

## 핵심 결과

| 항목 | 공식 sealed one-shot | adaptive 재측정 | 판정 |
|---|---:|---:|---|
| 수동 의미 정답 | 20/32 (62.5%) | 24/32 (75.0%) | adaptive만 +4, 공식 점수 불변 |
| 자동 의미 정답 | 7/32 | 9/32 | 표면값·골드 좌표 매칭 false negative가 많아 참고용 |
| false-full | 0 | 0 | 통과 |
| unsupported overclaim | 1 (slot 22) | 0 | 증가 없음, 개선 |
| 인용 좌표 복원 | 32/32 | 32/32 | 통과 |
| 생성 오류 | 0 | 0 | 통과 |
| Qwen 호출 | 32 | 32 | A3 0회, A4 정확히 32회 |
| p50 | 오염 측정 10.37초 | 10.07초 | 통과 |
| p95 | 오염 측정 332.73초 | 13.05초 | 통과 |
| 최대 | 336.2초 | 24.79초 | 통과 |
| 30초 초과 | 5건 | 0건 | 통과 |

adaptive 자동 실행기의 평균 입력 토큰은 2,020.375로 과거 보조 게이트 2,000을 20.375 토큰 초과했다. 이번 지시서의 A4 승격 게이트에는 포함되지 않지만 숨기지 않고 기록한다.

## A1·A2 적용

### A1 — 랭킹 문맥에 표 도입문 포함

- 커밋: `2c3b5c1` (`Include table introducers in Product RAG ranking`)
- 변경:
  - `src/v3/product_evidence_pack.py`
  - `tests/v3/test_product_table_subject_binding_runtime.py`
- 효과: `_ranking_context_text()`가 `표 도입:`을 버리지 않고 `context_text` 전체를 atomic evidence 랭킹에 사용한다.
- 표적 테스트: 5 passed

### A2 — 요구사항 예약 fallback

- 커밋: `2df32ac` (`Apply Product RAG requirement reservation fallback`)
- 변경:
  - `src/v3/product_free_rag.py`
  - `tests/v3/test_product_requirement_reservation_runtime.py`
- 효과:
  - `requirement_queries = kiwi_queries or explicit_question_clauses(question)`
  - 해석된 요구 절이 둘 이상이면 `atomic_reserve_per_query = 3`, 아니면 1
- 표적 테스트: 9 passed
- 주의: `product_free_rag.py`는 실행에 사용되던 미추적 파일이었기 때문에 이 커밋에서 현재 기준선 전체가 처음 Git에 등록됐다.

두 변경은 지시서대로 서로 다른 커밋이다.

## A3 — 결합 shadow, Qwen 0회

산출물: `product_free_rag_pending_combined_shadow_20260806.jsonl`

SHA-256: `59cc7902ab73df07439cc994610a93fcff45a4d3ebf7ec260c7416ec7ba2b565`

| arm | value_present full | partial | none |
|---|---:|---:|---:|
| 사전 등록 기준선 | 40 | 4 | 5 |
| A1 적용, A2 미적용 | 41 | 3 | 5 |
| A1+A2 결합 | **42** | **2** | **5** |

- 숫자·날짜·시각·화폐 감소: 0
- 서술형 진단 감소: 0
- Qwen 호출: 0
- A1 기준 A2 후보 rerank 평균 증가: 207.069ms/문항
- 사전 등록 판정: `42 이상`이므로 A4 진행 허용

두 변경은 shadow coverage에서는 상호보완이었다. A6-1 표 형제 행과 A6-26 가격 값이 각각 full coverage로 올라갔다.

## A4 — A6 32문항 adaptive replay

원시 산출물: `product_free_rag_a6_pending_adaptive_replay_20260806.jsonl`

SHA-256: `8cd93478c63da43c45cd0b3d6faf2f042eab91e344e6724e64acae31a1d76b23`

수동 검수: `product_free_rag_a6_pending_adaptive_manual_review_20260806.jsonl`

SHA-256: `bc5717eb33e34e779cd240705b778af2c8bd50fbe88ccbfbba2fef1f55f65c68`

수동 판정은 Codex가 질문·frozen 요구값·노출 답변·raw claim·rejected claim·evidence pack을 전수 대조한 adaptive 진단이다. 프로젝트 오너의 공식 adjudication이 아니며 공식 20/32를 덮어쓰지 않는다.

### 문항별 before → after

| slot | 공식 → adaptive | 요약 |
|---:|---|---|
| 1 | 오답 → 오답 | 네 값이 pack·raw claim에 복구됐지만 세 금액 claim을 verifier가 제거 |
| 2 | 오답 → **정답** | 14시 오답이 본문 15시로 교정 |
| 3 | 정답 → 정답 | 기간과 100% 유지 |
| 4 | 오답 → 오답 | 신고 경로 3단계 없음 |
| 5 | 정답 → 정답 | 채널·시각 유지 |
| 6 | 정답 → 정답 | slot 6 골드 정정 레이어 기준 균등 획득 답변 인정 |
| 7 | 오답 → 오답 | pack에는 20→18초가 생겼지만 Qwen이 본체도 12→9초로 오연결 |
| 8 | 정답 → 정답 | 40초·100% 유지 |
| 9 | 정답 → 정답 | 마일리지 조건 유지 |
| 10 | 오답 → **정답** | 10회·1회·06시 모두 노출; 근거 있는 루크 설명이 불필요하게 1문장 추가 |
| 11 | 오답 → 오답 | 판매 종료 8월 27일 누락 유지 |
| 12 | 정답 → 정답 | 미누적·06시 유지 |
| 13 | 오답 → **정답** | 연 5회 재발급까지 복구 |
| 14 | 오답 → 오답 | 필요한 두 확인 범위를 여전히 답하지 않음 |
| 15 | 정답 → 정답 | 경로·6자리 유지 |
| 16 | 정답 → 정답 | 세리아·앱 내 불가 유지 |
| 17 | 정답 → 정답 | 재료·소멸·교환 타입 유지 |
| 18 | 정답 → 정답 | 등장·제외·계약 효과 유지 |
| 19 | 정답 → 정답 | 음성 권한 유지 |
| 20 | 정답 → 정답 | I키·계정 공용 유지 |
| 21 | 정답 → 정답 | 60일·기한 경과 불가 유지 |
| 22 | 오답 → 오답(안전 개선) | 고객센터 대신 퍼스트 서버로 오답; 근거 없는 기한 claim은 차단 |
| 23 | 정답 → 정답 | 3회·전체 계정·가입 차단 유지 |
| 24 | 정답 → 정답 | 삭제·숨김 유지 |
| 25 | 정답 → **오답** | 강철 거푸집 `교환가능` claim이 relevance verifier에서 제거된 유일한 악화 |
| 26 | 오답 → **정답** | 9,800 세라·30일·보상 모두 복구 |
| 27 | 정답 → 정답 | 200·264칸·8,000 세라 유지 |
| 28 | 오답 → **정답** | 계정당 5회까지 복구 |
| 29 | 정답 → 정답 | 두 가격만 답한 정상 partial 유지 |
| 30 | 정답 → 정답 | 서버 표 복원 유지 |
| 31 | 정답 → 정답 | 두 계약 15일 유지 |
| 32 | 오답 → 오답(안전 유지) | +221과 비지원 제한을 한 claim에 섞어 전체 제거 |

집계:

- 복구: slot `2, 10, 13, 26, 28` — 5건
- 악화: slot `25` — 1건
- 순증: +4건, 20/32 → adaptive 24/32
- 남은 오답: `1, 4, 7, 11, 14, 22, 25, 32`

slot 10의 추가 루크 토벌전 문장은 질문과 무관한 품질 문제다. 다만 E3에 그대로 있는 사실이고 세 요구 정답을 모두 완성했으므로 의미 정답으로 판정하되 `grounded_but_irrelevant_extra_claim`으로 별도 기록했다.

### 안전 판정

- 자동 false-full 후보 slot 6은 frozen gold 오류를 반영하지 못한 결과다. 2026-08-06 확정 정정 레이어에 따라 수동 false-full은 0이다.
- slot 22가 생성한 `약 10일` 기한은 `factual_values_not_in_evidence`로 제거돼 사용자에게 노출되지 않았다.
- slot 29의 근거 없는 구매 제한과 slot 32의 혼합 claim도 노출되지 않았다.
- adaptive 수동 unsupported overclaim은 0건이다. 공식 1건보다 증가하지 않았다.

### 자동 채점 해석

자동 의미 정답 9/32는 최종 의미 점수가 아니다. 자동 통과 9건은 모두 수동 정답이었지만, 수동 정답 24건 중 15건을 표면값·acceptable coordinate 불일치로 놓쳤다. 따라서 자동 채점은 위양성 0, 위음성 15로 관찰됐으며 수동 의미 판정을 사용했다.

## A5 — R5 단계 귀속 before / adaptive

아래 adaptive 열은 현재 노출 답변 기준의 실패 지원 요구 8개를 센다. 기존 R5 실패 14개 중 7개가 해결됐고 7개가 남았으며, 공식 정답이던 slot 25에서 S4 실패 1개가 새로 생겼다.

| 단계 | 공식 one-shot 실패 요구 | adaptive 실패 요구 | adaptive 사례 |
|---|---:|---:|---|
| S1 검색 | 1 | 1 | slot 22 고객센터가 최종 후보에 없음 |
| S2 pack 선택 | 5 | 1 | slot 4 신고 경로 3단계가 pack에 없음 |
| S3 생성 | 3 | 3 | slot 7 본체 20→18초, slot 11 종료일, slot 14 확인 범위 |
| S4 verifier | 4 | 3 | slot 1 금액 3개, slot 25 교환가능, slot 32 혼합 claim 제거 |
| S5 관계 오연결 | 1 | 0 | 기존 slot 7의 질풍 요구 자체는 복구 |
| **합계** | **14** | **8** | 기존 미해결 7 + 신규 악화 1 |

### R5의 기존 실패 요구 14개 변화

| slot·요구 | 공식 단계 | adaptive 단계 |
|---|:---:|:---:|
| 1 transfer_limits | S2 | S4 — pack·raw 생성 복구 후 verifier 제거 |
| 2 maintenance_start | S3 | 해결 |
| 4 report_path | S2 | S2 유지 |
| 7 base_cooldown_change | S2 | S3 — pack 복구, 생성 오연결 |
| 7 gale_option_cooldown_change | S5 | 해결 |
| 10 daily_clear_requirement | S4 | 해결 |
| 10 daily_fishing_limit | S4 | 해결 |
| 11 sales_period | S3 | S3 유지 |
| 13 mypin_properties | S2 | 해결 |
| 14 available_views | S3 | S3 유지 |
| 22 bug_reporting_channel | S1 | S1 유지 |
| 26 contract_price_duration | S2 | 해결 |
| 28 tropical_hat_box | S4 | 해결 |
| 32 october_siv_fame | S4 | S4 유지 |

신규 악화 slot 25는 raw Qwen claim과 E5 근거가 모두 맞았으나 `evidence_relevance_below_threshold`로 차단됐다. 라이브 생성까지 다시 수행한 adaptive 결과이므로 이 한 번의 관찰만으로 A1 또는 A2가 원인이라고 단정할 수는 없다. 최종 손실 지점만 S4로 확정한다.

## 사전 등록 게이트

| 게이트 | 결과 | 판정 |
|---|---|---|
| 공식 정답 20건 악화 0 | slot 25 악화 1 | **실패** |
| false-full 0 | 0 | 통과 |
| overclaim 증가 0 | 1 → 0 | 통과 |
| p95 ≤ 30초 | 13.053초 | 통과 |
| 인용 좌표 32/32 | 32/32 | 통과 |
| 의미 정답 ≥ 80% | 24/32 = 75% | **실패** |

따라서 이 라운드의 최종 판정은 **NO-GO**다. 안전·지연·인용은 통과했지만 정확도와 무회귀 조건을 동시에 충족하지 못했다.

## 무결성·회귀

- A3 Qwen 호출: 0
- A4 Qwen 호출: 정확히 32
- 생성 오류·timeout: 0
- A4 사전 제품 회귀: 169 passed
- 최종 전체 v3: 1,264 passed, subtests 67 passed, 기존 manifest SHA 면제 2건만 실패
- frozen A6 SHA-256: `9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc` — 불변
- 공식 one-shot SHA-256: `1252ecda7546659b93c0253914541c045dbfadbac22477d0ed6e8d90db37c9c9` — 불변
- 공식 adjudication 산출물: 수정하지 않음
- `use_question_coverage_contract`: false 유지
- 검색 깊이: 변경 없음

- 이번 라운드로 생긴 새 회귀: 0

## 종료 결정

지시서의 한 라운드를 여기서 끝낸다. 이 결과를 보고 추가 수정·A6 재호출 라운드를 열지 않는다. 다음 작업은 공식 20/32와 adaptive 24/32, R5 2열 표, 지연 통제 결과, 측정기 한계를 포트폴리오에 서로 다른 성격의 숫자로 반영하는 것이다.
