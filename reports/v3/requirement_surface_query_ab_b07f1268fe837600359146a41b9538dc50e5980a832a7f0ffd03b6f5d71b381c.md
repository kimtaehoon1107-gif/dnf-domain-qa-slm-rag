# Entity-anchored requirement surface query A/B

Development-only. No runtime/canonical promotion.

Decision: **DEVELOPMENT_GO_NEW_REVIEWED_CANARY_REQUIRED**

| Block | Arm 0 strict | Arm 1 strict | Arm 0 literal | Arm 1 literal | Arm 0 false-full | Arm 1 false-full |
|---|---:|---:|---:|---:|---:|---:|
| Frozen docs | 63/69 | 63/69 | 20/69 | 20/69 | 49/69 | 49/69 |
| Authored adaptive | 21/24 | 21/24 | 9/24 | 10/24 | 13/24 | 12/24 |

- applied cases: `['authored_validation_v3_2_sha256_c0c2d4091eda6655d6e8f0bdbc01a155e39e637642f903e8da2d288fd6cac599']`
- strict regressions: `[]`
- literal improvements: `['authored_validation_v3_2_sha256_c0c2d4091eda6655d6e8f0bdbc01a155e39e637642f903e8da2d288fd6cac599']`

## 광휘의 행로 target

- original strict all-groups: **False**
- provisional equivalent-official all-groups (literal-span required): **True**
- acceptable sibling applied: **False**

Citations:

- - 명성 58,950 이상의 캐릭터로 탐사를 진행할 수 있습니다.
- - 탐사는 계정 단위로 진행되며, 한 번에 하나의 탐사만 진행할 수 있습니다.
- | 기억의 숲 탐사 | 평소 진입이 금지되었던 기억의 숲을 지나는 위험한 교역로. | 4시간 | 순례의 인장 120개 빛의 출정령 : 단기 1개 |
- | 종말의 계시 1개를 획득할 수 있습니다. |

## Gates

- frozen_strict_regression_zero: **True**
- frozen_literal_regression_zero: **True**
- authored_strict_regression_zero: **True**
- authored_literal_regression_zero: **True**
- authored_literal_improves: **True**
- new_false_full_zero: **True**
- target_both_literal_spans_cited: **True**
- target_provisional_sibling_requires_literals: **True**
- exact_all: **True**
- temporal_violation_zero: **True**

The authored 24 set is adaptive. A pass permits only a new reviewed canary; it does not promote runtime/canonical behavior.
