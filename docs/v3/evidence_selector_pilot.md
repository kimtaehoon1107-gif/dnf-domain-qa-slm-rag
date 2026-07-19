# DNF RAG v3 Answerability / Evidence Selector 파일럿

## 범위

이 사이클은 승격된 v3 hybrid 검색기의 top-10을 입력으로 사용하는 결정론적 answerability 기준선과 Evidence Selector 압축 후보만 측정한다. Router, decomposition, generator, verifier, 학습, 최종 blind 평가는 포함하지 않는다.

## Answerability 기준선

질문 문구만 사용해 다음 고신뢰 범주를 거절한다.

- 시스템 프롬프트·내부 평가 정보 요구
- 로또·금융·날씨 예측
- 개인 계정의 실시간 제재 상태
- 실시간 경매장 시세
- 악용 절차 요구
- 미래 직업 순위 같은 주관적 예측

공식 문서로 답할 수 있는 사실과 개인 판단을 함께 요구하면 `partial`, 공식 사실 요구는 `true`로 분류한다. 이 규칙은 고정 dev에 맞춰 만든 개발 기준선이며 독립 holdout 일반화 결과가 아니다.

고정 dev 결과는 true 47, partial 8, false 8을 모두 일치시켰고, false 8개에는 선택 근거를 노출하지 않았다. 하지만 `answerability_accuracy`만으로 성능을 판단하지 않으며 아래 selector 지표와 함께 보고한다.

## Evidence Selector 후보

선택 규칙은 gold chunk·document·source ID를 사용하지 않는다.

1. 승격 검색기의 top-10만 입력으로 받는다.
2. `hybrid base score × 0.75 + 질의 토큰 포괄률 × 0.25`로 결정론적으로 재정렬한다.
3. 상위 8개를 선택한다.
4. 구조화 질의의 parent-lead guard 청크가 빠졌다면 보존한다.

## 측정 결과

| 지표 | 검색 top-10 | selector |
|---|---:|---:|
| all-required-groups hit | 0.981818 | 0.981818 |
| evidence-group recall micro | 0.983051 | 0.983051 |
| 평균 후보 수 | 10 | 8.127273 |

- 후보 감소율: 0.187273
- 주석 근거 정밀도: 0.129754
- 주석 기준 noise rate: 0.870246
- semantic contradiction rate: 미측정

주석 근거 정밀도는 허용 chunk ID만 정답으로 세는 보수적 측정이라, 의미상 유효한 인접 근거도 noise로 계산될 수 있다. 그렇더라도 현재 수치는 Generator에 바로 넘길 만큼 깨끗하다고 볼 수 없다.

## 판정

- answerability dev baseline: GO
- selector compression candidate: GO
- production Evidence Selector: NO-GO
- Generator 진입: NO-GO
- 최종 benchmark: NO-GO

다음 단계는 새 기능을 더 붙이는 것이 아니라, 선택된 약 8개 근거의 의미상 지지 여부를 판별하는 reranker/entailment selector를 별도 A/B로 측정하는 것이다. 사람 검토가 대기 중인 공지 문항은 계속 dev refreeze에서 제외한다.

## 고정 산출물

- results: `data/v3/evidence/evidence_selector_pilot_results_c5f0f49ae0e519a8533d7672ba72208a73169c14263a3d77e70768ff6bef31e2.jsonl`
- manifest: `data/v3/evidence/evidence_selector_pilot_manifest_268a6e48243f6a21a5f36706692186af1a3081799d5b6f72de98948fe3fda16b.json`
- report: `reports/v3/evidence_selector_pilot_e902434a0de3eac720b5e3699d1fab5476f81b58b959234de355c5e47332c8e1.json`
