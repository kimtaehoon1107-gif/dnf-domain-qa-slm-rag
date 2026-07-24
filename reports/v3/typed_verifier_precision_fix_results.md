# Typed verifier 형식 매핑 정밀도 수정 결과

## 범위

`docs/v3/typed_verifier_precision_fix.md`의 통화·불리언 형식 매핑 버그 3종만
수정했다. 검색, 프롬프트, 모델, 후보 조립은 변경하지 않았다.

봉인된 generalization-64는 재실행하거나 새 verifier로 재채점하지 않았다.
기존 `37/64 = 57.8%` 결과는 해당 파이프라인 버전의 영구 기록으로 유지한다.

## 구현

- 공용 정규화 모듈 `src/v3/value_normalization.py` 추가
- 런타임 verifier와 generalization scorer가 같은 통화·불리언 함수를 사용
- 통화:
  - 단위 없는 모델 amount를 선택된 근거의 통화 amount 집합과 대조
  - 긴 단위를 먼저 매칭
  - `광휘의 잔영`, `골드 코인`, `세라 코인`, `마일리지`, `포인트`, `코인` 지원
  - `광휘의 잔영 120개` 같은 단위-우선 수량 형식 지원
- 불리언:
  - 동작 부정을 먼저 배타적으로 판정
  - `교환불가`, `거래불가`, `환불불가`, `사용불가`, `합성불가` 상태명사의
    `불가`를 부정 동작으로 오인하지 않음
  - `수정`, `개선`, `추가`, `변경`, `적용`, `포함`, `가능` 긍정 동작 지원
- scorer/normalization 버전을 v2로 올려 향후 결과가 기존 봉인 scorer와
  구분되도록 함

## 필수 재현표

다음 케이스를 단위 테스트로 고정했다.

```text
10 골드 코인                 -> {(10, 골드 코인)}
1500 마일리지                -> {(1500, 마일리지)}
12,900 세라                  -> {(12900, 세라)}
광휘의 잔영 120개            -> {(120, 광휘의 잔영)}

12900 + 12,900 세라          -> 통과
22600 + 22,600 세라          -> 통과
10 + 10 골드 코인            -> 통과
12900 + 99,999 골드          -> 거절

현상이 수정됩니다            -> True
거래타입 교환가능            -> True
교환불가 타입으로 변경       -> True
교환불가로 변경되지 않음     -> False
연출이 출력되지 않는 현상    -> False
결투장에서는 적용되지 않음   -> False
OTP 이용이 가능합니다        -> True
```

내부 정규화 함수뿐 아니라 실제 공개 verifier 진입점도 고정했다.

```text
12900 + "12,900 세라" evidence_ref
-> supported_exact

True + "교환불가 타입으로 변경됩니다" evidence_ref
-> supported_exact

True + "교환불가 상태로 변경되지 않습니다" evidence_ref
-> unsupported (typed_value_not_supported_by_evidence)
```

## adaptive-32 verifier-only replay

기존 Qwen 원출력을 재사용했고 새 LLM 호출은 0회다.

```text
기존 reverified-v2 SHA:
b6a8e2714a0c4d278f974ca3b7e93a53bc5eca26911acd6aa0bd8fe5506ea6cc

수정 후 verifier-only replay SHA:
b6a8e2714a0c4d278f974ca3b7e93a53bc5eca26911acd6aa0bd8fe5506ea6cc
```

두 파일이 바이트 단위로 동일했다. adaptive-32에는 이번에 추가한 형식이 없어
복구 문항도, 회귀 문항도 0건이었다.

## 회귀 검증

```text
관련 테스트:
24 passed, 7 subtests passed

전체 tests/v3:
669 passed, 54 subtests passed, 2 deprecation warnings
```

frozen-95의 mixed recall 및 docs false-partial 안전성 테스트도 전체 회귀에
포함되어 통과했다.

## 결론

지시된 형식 버그의 재현표는 모두 통과했고, 틀린 amount와 boolean 반대 방향은
계속 차단된다. 기존 adaptive-32와 frozen-95에는 회귀가 없다.

효과 크기는 봉인 64를 다시 사용하지 않고, 향후 새 human-reviewed holdout에서
처음 측정한다.

## 2026-07-25 사후 진단 부록

사용자 요청에 따라 저장된 64문항 후보와 모델 원출력에 현재 verifier를 적용하는
진단용 replay를 별도로 수행했다. 새 LLM 호출과 검색 재실행은 없었다.

진단 결과는 `40/64`로 기존보다 `+3`이었지만, 이미 공개된 세트의 사후 분석이므로
새 일반화 점수나 기준선으로 승격하지 않는다. 상세 내용은
`reports/v3/typed_evidence_ref_generalization_64_precision_fix_diagnostic.md`에
분리해 기록했다.
