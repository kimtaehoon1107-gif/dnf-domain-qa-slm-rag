# 지시서 — 두 아키텍처를 같은 문항·같은 지표로 나란히 측정

작성: 2026-07-23 · 대상: Codex · 상태: **측정 라운드 (사전 기준 등록됨)**

---

## 0. 먼저, 제가 앞서 한 제안을 정정합니다

저는 "각 단계 승자를 합치자"고 제안했습니다. **틀렸습니다.** 코드를 확인하니 두 경로는
한 파이프라인의 단계가 아니라 **서로 다른 아키텍처**입니다.

```
[A] 백본 경로   src/v3/gradio_backbone_demo.py + grounded_answer_generator.py
    검색 → planner 요구분해 → 리랭커 → 조립기 span → value-shape 게이트
         → 자유 텍스트 생성 → 기계적 숫자 대조

[B] simple RAG  src/v3/simple_domain_rag.py + generate_grounded_llm_answer.py
    검색(subject-anchored) → 후보 청크 통째로
         → JSON 스키마 출력(candidate_ref/quote) → exact citation 검증
```

**B는 조립기도 value-shape 게이트도 쓰지 않습니다.** 따라서 "A의 조립기 + B의 검색"
같은 조합은 성립하지 않습니다.

그리고 더 중요한 것:

> **B는 이미 청크를 통째로 줍니다.**
> `build_grounded_prompt(candidate_chunk_ids=..., chunks_by_id=...)`

제가 이번에 A에 도입해 정답을 16 → 26으로 올린 "chunk 스코프"는 **B가 처음부터 하던
방식**입니다. 즉 제 발견은 **A가 스스로를 좁히고 있었다**는 것이었고, 고친 결과 A가 B의
설계 쪽으로 수렴했습니다. B에 적용할 개선이 아닙니다.

---

## 1. 그래서 이번 라운드는 통합이 아니라 head-to-head

지금 두 아키텍처의 숫자는 **비교가 불가능합니다.**

| | A (백본) | B (simple RAG) |
|---|---|---|
| 문항 | frozen 95 중 gold 51문항 | requirement-surface canary 32문항 |
| 문항 겹침 | — | **0 / 32** (질문 텍스트 대조 확인) |
| 주 지표 | `gold_value_complete` — 답변에 gold 값이 다 있나 | `all_evidence_spans_hit` — gold 근거 span을 다 인용했나 |
| 현재 최고 | 정답 26 / 오답 12 / 무응답 13 | strict 15/32, false-full 6/32 |

**46.9%와 51.0%는 다른 문항, 다른 축입니다. 우열을 말할 수 없습니다.**

---

## 2. 할 일 — B를 frozen 95에서 돌린다

새 평가셋을 만들지 마세요. **얇은 어댑터 하나면 됩니다.**

`evaluate_simple_domain_rag.py`가 eval-set 행에서 읽는 필드는 넷뿐이고, frozen dev/canary
행에서 전부 유도됩니다.

| 필요 필드 | frozen 행에서 |
|---|---|
| `candidate_id` | `dev_id` |
| `slot_ordinal` | 행 순서 인덱스 |
| `gold_requirement_count` | `required_evidence_group_count` (없으면 `len(evidence_groups)`) |
| `is_table_source` | `source_ids` 기준 판정 |

실질 내용(`question`, `as_of`, `gold_answer`, `evidence_groups`, `gold_chunk_ids`,
`source_ids`, `time_scope`)은 **frozen 행에 이미 전부 있습니다.**

```bash
python src/v3/evaluate_simple_domain_rag.py \
  --eval-set <어댑터로 만든 frozen 95 파일> \
  --model qwen3-8b:ctx8192 --device cuda
```

어댑터 출력은 내용주소 JSONL로 동결하고, **frozen 원본은 건드리지 마세요.**

---

## 3. 두 지표를 모두 찍어야 합니다

각 아키텍처의 출력에 대해 **둘 다** 계산하세요.

**지표 1 — 인용 커버리지** (`all_evidence_spans_hit`, B의 기존 지표)
gold evidence span을 전부 인용했는가.

**지표 2 — 값 정확도** (`gold_value_complete`, A의 기존 지표)
```python
from src.v3.grounded_answer_generator import extract_factual_tokens
gold_tokens = [t for g in row["evidence_groups"]
                 for t in extract_factual_tokens(g.get("evidence_span") or "")]
correct = bool(gold_tokens) and all(
    _compact(t) in _compact(answer_text) for t in gold_tokens
)
```
답변 텍스트만 있으면 계산되므로 **B의 출력에도 그대로 적용됩니다.**

**고정 분모로 보고하세요.** gold 값이 있는 문항 전체를 분모로 두고
`정답 / 오답 / 무응답`을 각각 세십시오. "답한 것 중 맞은 비율"만 보고하면
**덜 답하는 쪽이 유리해 보이는 착시**가 생깁니다. 이번 세션에서 실제로 겪었습니다
(chunk+동결 68.4% vs chunk+value_first 60.5% — 정답 수는 26으로 동일했습니다).

---

## 4. 사전 기준 — 실행 전 확정, 사후 변경 금지

A의 실측치(frozen 95, gold 51문항, chunk 스코프, 동결 조립기, ctx8192 기준):

```
정답 26 / 오답 12 / 무응답 13     docs_only false_full 4/69     생성 오류 0
```

B를 같은 51문항에서 돌린 뒤:

| 결과 | 해석 |
|---|---|
| B 정답 ≥ 30 **AND** B 오답 ≤ 12 | **B 우세** — A를 접고 B로 통합 |
| B 정답 ≤ 22 **OR** B 오답 ≥ 20 | **A 우세** — B의 검색 개선만 A로 이식 |
| 그 사이 | **무결정** — 지표 1(인용 커버리지)과 false-full로 재판단 |

±1건은 노이즈입니다. 이번 세션에서 `num_ctx`만 바꿔도 1건이 뒤집히는 걸 확인했습니다
(temperature는 0으로 고정돼 있으므로 샘플링 잡음은 아닙니다).

---

## 5. 하지 말 것

- **새 평가셋을 만들지 마세요.** 문항이 또 갈라지면 이 문제가 반복됩니다.
- **출력 스키마 분리(`table_row_ref` 제거)를 이번에 같이 넣지 마세요.**
  A/B 판정과 스키마 효과가 섞입니다. 그 진단 자체는 정확하니 B가 이기면 그다음 라운드로.
- **subject-anchored 검색을 A에 이식하는 것도 이번이 아닙니다.** 4장 결과를 보고.
- 동결 산출물 재생성, 런타임 승격 금지.

---

## 6. 왜 이 순서인가

지금 저장소에 **생성기가 두 개** 있고, 각자 **다른 문항 집합**으로 평가되고 있습니다.
이 상태를 두면 이번 세션 내내 반복된 실패가 구조적으로 고착됩니다 —
격리에서는 좋아 보이는데 합치면 안 되는 상황.

한쪽을 접기 전에는 스키마 작업도, 검색 이식도 **어느 코드에 투자할지 모르는 채로 하는 것**입니다.

---

## 7. 인용하면 안 되는 숫자

**`73/82 = 89.0%`를 시스템 성능으로 쓰지 마세요.** Codex가 "직접 비교 불가"라고 한 것은
맞고, 한 걸음 더 나갑니다 — 이번 세션에서 그 숫자가 **부풀려졌음이 측정됐습니다.**

```
89.0%  (73/82)   청크 단위: 인용한 청크가 정답 목록에 있나만 봄
59.8%  (49/82)   span 값 형태: 그 안에 요구된 형태의 값이 있나
```

73의 실체는 docs_only 61 + mixed 과잉주장 10 + 부분정답 2였고, 61 중 값까지 맞는 건
47이었습니다. 근거는 `reports/v3/router_backbone_mixed_metrics_ab_b1cec58a….json`.

---

## 8. 이 세션의 방법론 교훈 (라운드 전적 1승 4패)

- **격리·소표본 프로브로 방향을 정하지 마세요.** Kiwi 조사 제거를 4건 프로브
  (0/4 → 2/4)로 정당화했다가 전체 95에서 50.0% → 42.9%로 악화시켰습니다.
  그 4건을 **실패 사례에서 골랐기 때문**입니다.
- **집계가 반증 사례를 가립니다.** "접두사 96.9% 일치"를 근거로 F1을 확신했는데,
  같은 출력에 `label == subject`(제거 실패) 사례가 있었고 결과는 0/33 → 0/33이었습니다.
- **측정 대상이 아닌 조건을 통제하세요.** 증거를 청크로 넓히면서 모델의 컨텍스트 창을
  확인하지 않았습니다. 잘림은 실재했지만(마커 테스트로 확인) 이번 결과에는 영향이
  없었습니다 — 즉 **방향은 맞고 크기를 틀렸습니다.**
- **유일하게 성공한 라운드**는 "명백한 버그를 고쳤고 부작용 0"인 경우였습니다
  (value-shape가 `06.25 ~ 07.30`과 `영구`를 duration으로 못 읽던 것).
