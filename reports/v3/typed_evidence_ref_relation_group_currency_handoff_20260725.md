# Typed evidence-ref verifier 수정 및 false-full 재검수 인계

작성일: 2026-07-25

## 가장 먼저 읽을 결론

봉인된 64문항의 공식 one-shot 결과는 계속 `37/64`이며 변경하지 않는다.
아래 `43/64`는 저장된 동일 Qwen3 8B 출력에 새 verifier만 적용한
**사후 진단 결과**다. 새 LLM 호출과 검색 재실행은 없었다.

```text
공식 봉인 결과: 37/64
verifier 사후 진단: 43/64
새 LLM 호출: 0
검색 재실행: 0
회귀: 0
```

## 이번에 바꾼 파이프라인

대상:

- `src/v3/typed_evidence_ref.py`
- `tests/v3/test_typed_evidence_ref.py`

변경 내용:

1. Boolean 근거를 같은 parent/chunk의 인접 evidence group으로 나눈다.
2. requirement의 subject와 relation에 맞는 group만 boolean 지지·모순
   판정에 사용한다.
3. 관계가 다른 부정 근거는 최종 인용에서도 제거한다.
4. 관계가 맞는 근거 안에서 긍정·부정이 충돌하면 fail-closed한다.
5. `price`와 `currency`의 숫자만 출력된 경우, 선택 근거에 동일 숫자와
   연결된 통화 단위가 하나뿐일 때만 단위를 복원한다.
6. 모델이 통화 단위를 명시했다면 근거의 `(금액, 단위)`와 정확히
   일치해야 통과한다.

이 수정은 임베딩 유사도로 부정을 판단하는 방식이 아니다. 숫자·통화는
결정론적 정규화를 사용하고, boolean은 relation-compatible evidence
group 단위로 판정한다.

## 64문항 사후 진단 결과

| 지표 | Typed 봉인 원결과 | verifier 수정 후 진단 |
|---|---:|---:|
| 후보 완전 보유 | 54/64 | 54/64 |
| 자동 핵심값 충족 | 37/64 | **43/64** |
| 승인된 직접 근거까지 적중 | 31/64 | **37/64** |
| verifier overreject | 14 | **8** |
| 생성 오류 | 3 | 3 |
| 자동 frozen-gold false-full flag | 1 | 1 |
| 평균 / p95 | 24.20초 / 44.67초 | 동일 |
| 전체 토큰 | 273,998 | 동일 |

복구 문항:

```text
12, 15, 35, 52, 54, 58
```

38번은 정답 상태를 유지하면서 관계가 다른 방해 근거를 제거하고
relation-compatible 근거만 인용하게 됐다.

테스트:

```text
24 tests passed
7 subtests passed
python compile checks passed
git diff --check passed
```

진단 산출물:

- `reports/v3/typed_evidence_ref_generalization_64_relation_group_currency_v2.md`
- `reports/v3/typed_evidence_ref_generalization_64_relation_group_currency_v2.json`
- `outputs/v3/diagnostics/typed_evidence_ref_generalization_64_relation_group_currency_v2.jsonl`

## 이전 split-schema와 현재 Typed 진단 비교

주의: split-schema는 원래 실행 결과이고, Typed `43/64`는 verifier-only
사후 replay다. 따라서 완전히 동일한 scorer로 다시 실행한 정식 A/B는 아니다.

| 지표 | 이전 split-schema 원결과 | Typed 원결과 | Typed 현재 진단 |
|---|---:|---:|---:|
| 후보 완전 보유 | 54/64 | 54/64 | 54/64 |
| 자동 핵심값 충족 | 38/64 | 37/64 | **43/64** |
| 승인된 직접 근거까지 적중 | 36/64 | 31/64 | **37/64** |
| verifier overreject | 8 | 14 | **8** |
| 생성 오류 | 5 | 3 | **3** |
| 평균 시간 | **15.36초** | 24.20초 | 24.20초 |
| p95 | **26.53초** | 44.67초 | 44.67초 |

현재 정확성 진단은 Typed가 우세하고, 속도는 split-schema가 우세하다.
정식 비교가 필요하면 split-schema 저장 출력도 현재 의미 채점 정책으로
replay해야 한다.

## false-full 용어와 출처 재검수

기존 비교 보고서의 `실제 false-full` 표기는 과도하게 확정적이었다.
자동 scorer가 검출한 것은 우선 다음 의미의
`frozen-gold false-full flag`다.

```text
동결 골드: 해당 requirement는 unsupported
시스템: supported로 답해 full answer 노출
```

동결 골드가 유효한 공식 근거를 빠뜨렸다면 내용상 오답이 아니므로,
자동 flag와 사람의 공식 출처 재검수 결과를 분리해야 한다.

### 이전 split-schema 31번

- 자동 판정: false-full
- 답변: 아바타 프리셋 최대 `10개`
- 공식 근거: “아바타 프리셋은 캐릭터당 최대 10개까지 확장 가능”
- 출처: 던파 공식 세리아 상점
  `[아이템]변경&확장(확장)`
  https://df.nexon.com/community/news/seriashop/639
- 재검수: **골드의 허용 근거 누락으로 판단. 실제 오답 아님.**

### 이전 split-schema 55번

- 자동 판정: false-full
- 질문 relation: 하트비트 메가폰 10개의 `계정 구매 제한`
- 모델 답변: `무제한`
- 공식 표 헤더:
  `아이템 명칭 | 아이템 가격 | 거래타입 | 아이템 설명 | 기간제한 | 비고`
- 해당 행의 `무제한`은 `기간제한` 열의 값이며 계정 구매 제한이 아니다.
- 출처: 던파 공식 세리아 상점
  `[아이템] 기타`
  https://df.nexon.com/community/news/seriashop/641
- 재검수: **실제 relation/column false-full.**

### Typed 47번

- 자동 판정: false-full
- 질문: 게임 이용제한 이의신청 경로와 정확한 처리 기한
- 모델 근거:
  - “이용제한 재조사를 위해 1:1문의를 접수한 경우”
  - “유형에 따라 3~5일 정도 소요될 수 있는 점 참고 부탁드립니다.”
- 출처: 던파 공식 FAQ
  `[게임이용제한] 이용 제한 해제를 어떻게 하나요?`
  https://df.nexon.com/customer/faq?faq_no=4860
- 재검수: **공식 근거가 질문 relation과 처리 기간을 직접 연결한다.
  골드의 허용 근거 누락으로 판단하며 실제 오답으로 보지 않는다.**

출처 재검수 기준 잠정 집계:

| 구성 | 자동 frozen-gold flag | 공식 출처 재검수상 실제 false-full |
|---|---:|---:|
| 이전 split-schema | 2 | **1** — 55번 |
| Typed evidence-ref | 1 | **0** |

단, 이 재검수는 동결 gold를 수정한 것이 아니다. 공식 점수와 SHA는 그대로
보존하고, 향후 사람 승인 절차를 거쳐 `acceptable_evidence_units`를 보완해야
한다.

## 다음 작업자가 지켜야 할 것

1. `37/64`를 공식 봉인 one-shot 결과로 계속 표시한다.
2. `43/64`는 반드시 `verifier-only post-hoc diagnostic`이라고 표시한다.
3. 자동 false-full flag를 곧바로 실제 의미 오답이라고 부르지 않는다.
4. 31·47번은 gold 누락 후보, 55번은 실제 표 열/relation 오류로 구분한다.
5. 봉인 64문항이나 기존 결과 파일을 조용히 수정하지 않는다.
6. 새 A/B가 필요하면 저장된 두 Arm 출력을 같은 최신 scorer로 replay한다.
