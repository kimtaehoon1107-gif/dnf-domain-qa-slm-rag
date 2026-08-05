# Product Free RAG 랭킹 문맥 결합 재평가 — 2026-08-05

## 결론

1단계는 **NO-GO**다.

- 게이트 1 실패: 표 도입문을 랭킹 문맥에 포함해도 A6-7 첫 절의 정답 E3
  `189-224`는 1위가 아니라 2위였다.
- 게이트 2 통과: numeric·date·time·currency 판정 대상의 `value_present`
  감소는 0건이었다.
- A6-7 최종 pack에서 E3의 제시 위치는 A/B 모두 세 번째였다.
- Qwen 호출은 0회다. 사전 등록 중단 규칙에 따라 2단계 A6-7 라이브는
  실행하지 않았다.
- 제품 런타임은 수정하지 않았다.

따라서 도입문 랭킹 결합은 A6-7을 해결하는 레버가 아니며, 지시서의 0절 정지
조건을 적용한다. **A6-7 계열은 이 라운드로 종료한다.**

이번 결과는 R2 당시 기각 판단이 틀렸다는 뜻이 아니다. 당시에는 pack 변경
규모만 측정할 수 있었고, 이번에는 R1·헤더 필터가 반영된 현재 조건에서
`value_present`로 변화의 방향까지 새로 측정했다.

실행 원본:

- `reports/v3/product_free_rag_ranking_context_reeval_20260805.jsonl`

## 실험 조건

- A 현행: `_ranking_context_text()`가 `표 도입:` 구간을 랭킹 입력에서 제거
- B shadow: 랭킹에 전체 `context_text` 사용
- 고정 항목:
  - 후보 청크
  - BGE reranker
  - prefilter 32
  - 요구별 reserve 수
  - evidence pack 최대 8개
  - R1 괄호 값 결합
  - R2 표 도입문 Qwen 문맥 결합
  - 헤더 메타데이터 필터
- `use_question_coverage_contract=False` 유지
- Qwen 호출: 0회
- 런타임 변경: 없음

## A6-7 첫 절 랭킹

첫 절:

> 6월 18일 브레이커 조정에서 타이드 바운드 쿨타임은 어떻게 줄었고

정답 unit:

```text
chunk_sha256_b85c… / 189-224
- 타이드 바운드 - 쿨타임이 감소합니다. (20초 → 18초)
```

### 조건 A — 현행

| 순위 | 좌표 | 점수 | 근거 요약 |
|---:|---|---:|---|
| 1 | `273-430` | 0.97773701 | 질풍 옵션 표 행, 12초→9초 |
| 2 | `488-653` | 0.91997129 | 격랑 옵션 표 행 |
| 3 | **`189-224`** | 0.89716947 | **타이드 바운드 20초→18초** |

### 조건 B — 전체 도입문 랭킹

| 순위 | 좌표 | 점수 | 근거 요약 |
|---:|---|---:|---|
| 1 | `273-430` | 0.96840727 | 질풍 옵션 표 행, 12초→9초 |
| 2 | **`189-224`** | 0.89716947 | **타이드 바운드 20초→18초** |
| 3 | `1013-1094` | 0.85908735 | 질풍 습득 후 쿨타임 감소량 오류 수정 |

도입문 결합은 오답 표 행의 점수를 `0.9777→0.9684`로 낮추고 정답 E3를
3위에서 2위로 올렸다. 그러나 오답 표 행이 여전히 1위다. 사전 등록 게이트는
정답 E3의 1위를 요구하므로 실패다.

최종 evidence pack의 E3 제시 순서:

| 조건 | E3 위치 |
|---|---:|
| A 현행 | 3번째 (`E3`) |
| B full context | 3번째 (`E3`) |

즉 랭킹 내부 순위 변화가 최종 pack의 표시 순서까지 바꾸지는 못했다.

## value_present

측정 가능한 요구는 49개다.

| 조건 | full | partial | none |
|---|---:|---:|---:|
| A_current 기준선 | 40 | 4 | 5 |
| A 현행 재생 | 40 | 4 | 5 |
| B full context | **41** | **3** | 5 |

변화는 한 건뿐이다.

| 문항 | 요구 | A | B | 판정 |
|---|---|---|---|---|
| A6-1 | `transfer_limits` | partial | full | 개선 |

- numeric·date·time·currency 감소: 0건
- descriptive 감소: 0건
- descriptive 진단 대상 A6-17·29: 변화 없음

따라서 **게이트 2는 통과**한다. 도입문 랭킹 결합은 현재 A6에서 값 근거를
밀어내지 않았고 한 요구를 개선했다. 하지만 이것은 A6-7 게이트 실패를
상쇄하지 않는다.

## A6 pack 변경 전건

좌표 집합 변경 12문항:

```text
A6-1, A6-6, A6-7, A6-18, A6-20, A6-21,
A6-22, A6-25, A6-27, A6-28, A6-29, A6-31
```

집합은 같고 순서만 변경된 2문항:

```text
A6-8, A6-17
```

변경된 모든 문항의 요구별 `value_present` 전후:

| 문항 | 요구 | A → B |
|---|---|---|
| A6-1 | transfer_limits | partial → **full** |
| A6-6 | primal_will_shop_terms | full → full |
| A6-6 | primal_oath_exact_probability | unsupported → unsupported |
| A6-7 | base_cooldown_change | full → full |
| A6-7 | gale_option_cooldown_change | full → full |
| A6-8 | countdown_duration | full → full |
| A6-8 | gauge_recovery | full → full |
| A6-17 | required_materials | full → full |
| A6-17 | material_consumption | boolean 제외 → boolean 제외 |
| A6-17 | mold_trade_types | partial → partial |
| A6-18 | appearance_condition | full → full |
| A6-18 | excluded_dungeons | full → full |
| A6-18 | contract_effects | full → full |
| A6-20 | inventory_key | full → full |
| A6-20 | soul_cube_storage | full → full |
| A6-21 | account_theft_recovery_request_period | full → full |
| A6-21 | account_theft_recovery_after_deadline | boolean 제외 → boolean 제외 |
| A6-22 | bug_reporting_channel | none → none |
| A6-22 | bug_report_response_deadline | unsupported → unsupported |
| A6-25 | normal_mold | full → full |
| A6-25 | steel_mold | full → full |
| A6-27 | vault2_unlock | full → full |
| A6-27 | vault2_stage16 | none → none |
| A6-28 | tropical_hat_box | full → full |
| A6-29 | august_special_box_prices | none → none |
| A6-29 | august_special_box_account_limits | unsupported → unsupported |
| A6-31 | grand_master_contract_contents | full → full |

## candidate rerank 시간

A6 32문항의 atomic evidence pack 구성 시간을 같은 프로세스에서 측정했다.

| 조건 | 합계 | 평균/문항 |
|---|---:|---:|
| A 현행 | 35,172.402ms | 1,099.138ms |
| B full context | 36,509.320ms | 1,140.916ms |
| 증가 | **1,336.918ms** | **41.779ms** |

시간은 사전 등록 게이트가 아니다. 실행 순서와 모델 워밍 상태의 영향을 받는
진단값이므로 제품 지연 기준선으로 사용하지 않는다.

## 현재 저장 사례 변경 규모

R1 시점에 고정된 저장 사례 인벤토리를 현재 atomic unit 구성으로 재생했다.

| 항목 | 현재 재측정 |
|---|---:|
| 고유 사례 | 248 |
| 저장 레코드 | 1,302 |
| 도입문 후보가 있는 고유 사례 | 184 |
| pack 집합 변경 | 44개 고유 사례 / **195개 레코드** |
| 순서만 변경 | 13개 고유 사례 / 37개 레코드 |

R2 당시 참고치는 pack 집합 변경 `246/1,300`이었다. 현재는 `195/1,302`로
변경 규모가 줄었다. 이는 헤더 필터와 R1 이후 조건에서의 재측정이며, 당시
판정의 오류를 뜻하지 않는다.

## 게이트와 분기

| 게이트 | 결과 | 근거 |
|---|---|---|
| 1. A6-7 첫 절 1위가 E3 `189-224` | **FAIL** | B에서도 2위 |
| 2. numeric·date·time·currency 감소 0 | PASS | 감소 0건 |

두 게이트를 모두 통과해야 2단계로 갈 수 있으므로:

- A6-7 조건 B 라이브: 실행하지 않음
- Qwen 호출: 0회
- 런타임 적용: 없음
- A6-7 추가 의미 정확도 라운드: 열지 않음
- 0절 정지 조건: **적용**

A6-7에는 정답 근거가 pack에 있고 요구별 예약과 claim 분리도 작동했지만,
8B 모델에 전달되는 우선 근거가 여전히 오답 표 행이다. 도입문 결합만으로
이를 뒤집지 못했으므로 이 실패는 현재 8B 파이프라인의 근거 선택 한계로
기록한다.

다음 우선순위는 지시서대로 의미 정확도 추가 수정보다 **tail 지연 원인 규명**이다.

## 검증

- 진단 단위·관련 회귀: 12 passed
- 전체 `tests/v3`: 1,245 passed, 67 subtests passed
- 첫 진단 시도는 결과 저장 전 표면 질의 폴백 누락으로 중단됐으며, 진단
  추출기만 수정해 처음부터 재실행했다. 두 시도 모두 Qwen 호출은 0회다.
- 기존 manifest SHA 면제 2건만 실패했으며 새 실패는 0건이다.
