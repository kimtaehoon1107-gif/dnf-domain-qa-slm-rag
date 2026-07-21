# Router backbone + answer-source A/B

- classifier recommendation: **REJECT_ANSWER_SOURCE_CLASSIFIER**
- backbone decision: **GO_DEVELOPMENT_BACKBONE_NO_GO_RUNTIME_DUE_TO_FALSE_FULL_AND_CROSS_PARENT**

| metric | Arm0 | Arm1 front | Arm1 post-search |
|---|---:|---:|---:|
| answerable overreject | 0/82 | 13/82 | 0/82 |
| expected-doc req suppressed | 0 | 22 | 0 |
| grounded docs | 73/82 | 61/82 | 73/82 |
| reject correct | 11/11 | 7/11 | 7/11 |
| realtime preferred route | 0/2 | 2/2 | 2/2 |
| honest-correct total | 86/95 | 70/95 | 82/95 |

No canonical/runtime promotion, model inference, training, keyword addition, or sealed run occurred.
