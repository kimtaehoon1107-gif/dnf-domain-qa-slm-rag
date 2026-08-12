# Claim evidence_ref 최소성 P3 검증 결과 (2026-08-12)

## P2 추가 회귀

- `complete=True`인 evidence unit 12개를 인용한 claim이 12개를 그대로
  유지하는 회귀 테스트를 추가했다.
- `tests/v3/test_product_free_rag.py`: 147 passed.
- verifier 관련 회귀 묶음: 209 passed.
- Qwen 호출: 0회.

## 봉인 A6 저장 출력 재채점

- 저장 출력 32/32 재채점 완료, 생성 호출 0회.
- 자동 채점 7/32, 기존과 동일.
- non-overclaim 판정 변화 슬롯 0.
- 인용 좌표 32/32.
- 공식 사람 감수 sealed 20/32는 변경하지 않았다.
- 봉인 파일 6개 SHA-256 재확인: 6/6 일치.

산출물:

- `reports/v3/claim_evidence_ref_minimality_a6_saved_rescore_20260812.jsonl`
- SHA-256:
  `a57327cb599b05de1604fb033259ad18d762684df85c8009ac29e859a908fa43`

## Adaptive 32

- 32/32 완료, Qwen 32회, 생성 오류 0.
- 인용 좌표 32/32.
- p50 12.058초, p95 16.593초, 최대 40.807초(slot 1).
- 자동 의미 채점은 0/32로 출력됐지만 이전 24/32와 비교 가능한 점수가 아니다.

### 비교 불가 원인

이번 실행은 비교 기준과 코퍼스·청크 fingerprint가 다르다.

| 실행 | document corpus SHA | chunk SHA |
|---|---|---|
| 이전 비교 기준 | `d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d` | `bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885` |
| 이번 실행 | `4643779c84879b9f9e81e9fd483fbc6dd4535a3c5ddd84c04872851c815c5de5` | `45030e5688ddcd3edc051ce383083248b13a0c6fcc85c3b9b1dae49d21f1dcd7` |

frozen A6의 acceptable chunk ID는 이전 코퍼스 기준이므로, 새 코퍼스에서
원문 좌표가 정확해도 scorer의 `evidence_complete`가 실패한다. 따라서 자동
0/32를 P2 회귀나 실제 의미 정확도 0으로 해석하면 안 된다.

### P2 영향 분리

- 이번 adaptive 32의 동일 raw output과 evidence pack을 최소화 ON/OFF로
  재검증했다.
- mode·claim text·evidence_refs 차이 슬롯: **0/32**.
- 즉 이번 adaptive 답변 변화는 P2 최소화 코드가 만든 것이 아니다.
- 이전 코퍼스 저장 출력에서는 최소화 영향이 slot 6과 27 두 건뿐이었다.
  - slot 6: `[E1,E5] -> [E1]`
  - slot 27: `[E4,E6] -> [E4]`
  - 두 슬롯 모두 mode와 claim text는 불변이었다.

### 이전 2026-08-10 adaptive 대비 변화

- 답변 text 변화 슬롯(27):
  `1,2,3,5,6,7,8,9,10,12,13,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,31`
- 답변 text 불변 슬롯(5): `4,11,14,30,32`
- mode 변화 슬롯(19):
  - `6 answer->partial`
  - `7 answer->unsupported`
  - `8 answer->unsupported`
  - `9 answer->unsupported`
  - `10 answer->unsupported`
  - `12 answer->partial`
  - `15 answer->unsupported`
  - `17 answer->unsupported`
  - `18 answer->partial`
  - `20 answer->unsupported`
  - `21 answer->partial`
  - `22 partial->unsupported`
  - `24 answer->unsupported`
  - `25 answer->unsupported`
  - `26 answer->unsupported`
  - `27 answer->partial`
  - `28 answer->partial`
  - `29 partial->unsupported`
  - `31 answer->unsupported`

산출물:

- `reports/v3/claim_evidence_ref_minimality_a6_adaptive_replay_20260812.jsonl`
- SHA-256:
  `7b5d0da8d858da4bbad6865d4780b8648cdaf77c5f74757d4e86ee984c6655b1`

## 데모 10번 (2026-08-12, 별도 세션에서 라이브 재확인)

Qwen 2회 사용(예산 초과분은 검증 목적의 재시도이며 사유를 아래에 남긴다).

1차 시도는 실행 중이던 서버 프로세스가 P2 코드 작성(19:35) 이전인 18:27에
기동돼 있어 옛 코드로 응답했다 — `pruned_evidence_refs: []`,
`rebound_evidence_refs: []`. 서버를 재기동해 2차 시도를 진행했다.

2차 시도(최신 코드, corpus SHA `4643779c...`, chunk SHA `45030e5688...`) 결과:

```
evidence_refs   [E1,E3,E5,E6,E7,E8]  (6개, 축소되지 않음)
pruned_evidence_refs   []
rebound_evidence_refs  []
mode   answer
```

`_replacement_evidence_for_claim`, `_claim_evidence_surface_coverage`를 실제
코퍼스 청크와 함께 직접 호출해 원인을 추적했다.

```
1. _replacement_evidence_for_claim은 E1을 최선의 단일 후보로 선정한다
   (identity_overlap=6, 조건·주어·관계·숫자값 검사 전부 통과)
2. 그러나 _claim_evidence_surface_coverage가 E1 단독 커버리지와 원본
   6개 근거의 합산 커버리지를 비교해 불일치를 발견한다
   (missing tokens: {'8월', '20일'})
3. E1 자신의 본문("이벤트 창을 통해 받은 보상은 우편함으로 지급됩니다.
   (우편 보관 기간 15일)")에는 시작일(8월 6일)이 없다. 시작일은 문서
   제목/heading에만 있고, identity_overlap 계산에는 제목이 포함되지만
   surface-coverage 계산에는 본문 text만 포함된다.
4. 커버리지 불일치로 축소가 거부되고 원본 6개가 그대로 유지된다.
```

**결론: 이것은 P2의 결함이 아니라 커버리지-동일성 가드가 의도대로
작동한 것이다.** 이 claim은 시작일·종료일 두 값을 함께 말하는데, 이
코퍼스에는 두 값을 한 문장 안에서 같이 말하는 근거가 없다(종료일은 E3
본문에, 시작일은 페이지 제목에만 있음). 단일 근거로 강제 축소하면
"8월 20일까지"라는 답의 근거 문장에서 날짜가 사라지는 false-full을
만들었을 것이다.

**정정**: 이번 라운드 초기에 이 사례의 목표를 `[E1..E8] -> [E3]`로 잡았던
것은 부정확했다. E3 단독으로는 시작일을 증명하지 못하므로, 정확한 최소
근거는 단일 근거가 아니라 `{E1, E3}` 같은 부분집합이다. P2는 **단일 근거
축소만** 다루도록 설계됐으므로(P1에서 의도적으로 범위를 좁힘), 이 사례는
이번 범위 밖이다. `test_product_verifier_minimizes_redundant_refs_after_condition_pruning`
회귀 테스트는 합성 데이터에서 E3 본문에 두 날짜를 모두 넣어뒀기 때문에
메커니즘 자체는 유효하게 검증하지만, 이 실사례의 근거 텍스트 구성과는
다르다는 점을 여기 기록한다.

## 판정

- P2 최소화 변경: **채택**. 회귀 0, sealed 불변, 같은 출력 ON/OFF 비교에서
  의미·mode 변화 0. 라이브 재확인에서도 안전장치가 의도대로 보수적으로
  작동함을 확인했다.
- 이번 adaptive 수치: **벤치마크 판정에 사용 금지**. 코퍼스 fingerprint가 달라
  이전 24/32와 직접 비교할 수 없다.
- 데모 10번(미카엘라 이벤트 기간): 이번 P2로는 해결되지 않는다. 부분집합
  최소화가 필요하며, 이는 별도 라운드로 남긴다.
- P3 전체: **완료**. live 데모 재실행 완료, 결과가 기대와 달랐던 원인까지
  추적해 기록했다. 동일 fingerprint adaptive 비교(자동 채점기 accepted-chunk-ID
  재보정)만 별도 라운드로 남는다.
