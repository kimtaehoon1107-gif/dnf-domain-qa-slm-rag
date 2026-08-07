# Subject-anchored full Arm + split evidence schema 분석

> **정정:** 이 보고서는 `all_evidence_spans_hit`를 답변 정확도처럼
> 해석한 오류가 있어 성능 해석이 폐기되었습니다. 해당 값은
> gold-span 문자 일치율이지 답변 의미 정확도가 아닙니다. 수정된 32문항
> 의미 재감사는
> `split_schema_requirement_generation_subject_arm_32_semantic_reaudit.md`를
> 기준으로 합니다. 원래 기록은 실험 이력 보존을 위해 아래에 남깁니다.

## 결론

**NO-GO. 라이브에는 승격하지 않는다.**

비표 `quote-only` / 표 `table-row` 스키마 분리는 원래의 스키마 혼입
문제를 해결했다. 비표 56회 호출에서 `table_row_ref` 출력은 0건이었다.
그러나 비표 exact quote 복사와 answer-token 게이트에서 과잉 거절이 발생해
전체 제품 경로는 기존 최선보다 회귀했다.

## 고정한 조건

- 모델: `qwen3-8b:ctx8192`
- 검색 후보: `simple_subject_anchored_retrieval_ab_cases.jsonl`의
  `arm_candidate_ids`
- 후보 회수: 31/32, 회귀 0
- 요구사항: 사람 검수된 32문항의 64개 요구를 그대로 사용
- 문항별 후보 수: 5~8개
- 변경 변수: 서버가 선택하는 evidence schema만 분리
  - 비표: quote만 허용
  - 표: table row ref 허용
- 라이브 코드: 변경하지 않음

## 전체 결과

| 지표 | 결과 |
|---|---:|
| 후보 보유 | 31/32 |
| strict literal | 14/32 |
| 후보 보유 조건 strict literal | 14/31 |
| 기존 strict literal | 12/32 |
| strict 개선 | 7건 |
| strict 회귀 | 5건 |
| strict false-full | 4건 |
| full / partial / abstain | 18 / 10 / 4 |
| citation precision | 57.6% |
| exact citation slice | 100% |
| 생성 오류 | 0 |

strict false-full 4건은 같은 의미가 아니다.

- 11번: gold의 불릿 `- `만 빠진 제품 정답
- 23번: gold에 빠진 동등한 최신 공식 청크를 인용한 제품 정답
- 29번: 다른 공식 문서의 동등한 판매 기간을 인용한 제품 정답
- 12번: 답은 맞지만, 선택한 인용이 해당 아이템이 `첫 구매 혜택`이라는
  관계를 직접 증명하지 못함

따라서 답 내용 기준으로는 네 건 모두 정답이지만, 근거가 요구 관계를
직접 증명하는지까지 보면 12번 1건은 실제 grounding false-full로 본다.

## 표와 비표

| 구간 | 문항 | 요구 | 기존 strict | 새 strict | strict false-full |
|---|---:|---:|---:|---:|---:|
| 표 | 4 | 8 | 3/4 | **4/4** | **0** |
| 비표 | 28 | 56 | 9/28 | 10/28 | 4 |

표 25~28번은 모두 full·strict 정답이었다. 26번을 새로 성공시켜 표 구간은
순개선 +1, 회귀 0이었다. 다만 일부 답변이 요구한 속성 외에 같은 표 행의
다른 속성까지 함께 출력해 답변 청결성은 추가 개선이 필요하다.

비표에서는 다음 verifier 실패가 발생했다.

| 실패 이유 | 요구 수 |
|---|---:|
| `answer_tokens_not_contained_in_evidence` | 11 |
| `quote_not_exact_contiguous_source_text` | 9 |

대표적으로 14·16번은 모델이 부정 문장을 읽고 `false`라고 올바르게
답했지만, `false`라는 토큰이 인용문에 없다는 이유로 전부 차단됐다.
21·22·24번은 정답 내용을 생성했지만 섹션 번호나 공백을 원문과 다르게
복사해 exact quote 검증에서 partial이 됐다.

운영정책 21~24번은 raw 생성 의미 기준 4/4였으나, 검증 후 제품 full은
1/4였다. 기존 최선 경로의 제품 4/4보다 명백한 회귀다.

## 판정

- 스키마 격리: **성공**
- 표 전용 branch: **유망하지만 표 4문항만으로 라이브 승격 불가**
- 비표 요구별 generator: **NO-GO**
- 전체 arm: **NO-GO**
- 기존 라이브 최선 구성: **유지**

다음에 비표 요구별 generator를 다시 시험한다면 verifier를 느슨하게
만드는 대신, 모델이 문자열을 재입력하지 않도록 서버가 미리 만든 짧은
`evidence_ref`를 선택하게 해야 한다. 그러면 선택된 ref를 서버가 원문의
정확한 span으로 복원할 수 있어 quote 복사 실패를 구조적으로 제거할 수
있다.

## 아티팩트

- reviewed SHA-256:
  `0498fbd582709294af473865c48208fa889b6200c9782a55829e30300c808aef`
- candidate pools SHA-256:
  `5612d446b6b14715bfb34ac67a7d7dcb0b66c71e81d1e5c7fcaf1db83e7da07a`
- result SHA-256:
  `16d3e62668bf71a59d938734922db2b072fb01756ceb8579f27f405eba770293`
- summary SHA-256:
  `19b3a8983c27009ae2fee7daadb3b6d0ad6b4490088e47dc7eecc6105a222958`
