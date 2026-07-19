# DNF RAG v3 requirement-slot claim coverage pilot

## 판정

- Round 4 claim-coverage: **NO-GO**
- 새 40-canary: **NO-GO**
- selected overlap threshold: 0.5

## 강등 32-set same-parent multi-field

- rows: 15
- cited groups: 19 → 17 / 35
- claim complete rows: 3 → 2 / 15
- slot recall: 32/50
- slot precision: 34/46

## 안전성

- 32 single-field regressions: 2
- 63 single-field regressions: 7
- runtime false citations: 0
- strict unsupported slot citations: 29
- false partials: 17
- partial disclosure 32: 12/12
- partial disclaimer 32: 5/5
- partial disclaimer 63: 8/8

runtime slot coverage에는 gold chunk/document/source ID를 전달하지 않았다.
모든 새 claim은 canonical chunk의 연속 원문이며 자유형 생성은 사용하지 않았다.
이 결과는 adaptive validation이며 final benchmark 성능이 아니다.
