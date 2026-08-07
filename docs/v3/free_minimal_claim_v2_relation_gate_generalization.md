# 지시서 — free_minimal_claim_v2 relation 게이트 일반화

작성: 2026-07-30 · 대상: Codex · 상태: 진단 완료, 수정 요청
대상 파일: `src/v3/free_minimal_claim_v2.py` (`_resolved_live_requirements`),
참조: `src/v3/claim_contract_relation_registry.py`

---

## 0. 배경 — 왜 이 조사를 했는가

사용자가 Gradio 데모(`app/free_minimal_claim_v2_demo.py`, 오늘 최신)에서 "디레지에
난이도 뭐뭐있어" 같은 일반 자유질문에 답을 못 받는다고 보고했습니다. Claude가 실제
실행 경로를 코드로 추적해 정확한 원인을 확정했습니다.

---

## 1. 확인된 원인

`src/v3/free_minimal_claim_v2.py`의 `_resolved_live_requirements` (라인 192~229 부근):

```python
def _resolved_live_requirements(requirements, *, question):
    normalized = []
    for requirement in requirements:
        row = dict(requirement)
        if "강화" in question and "확률" in question:      # ① 개별 질문 키워드 하드코딩
            row["relation"] = "enhancement_probability"
            row["value_type"] = "percentage"
        contract = relation_contract(row)
        if contract is None:
            allowed_types = _SAFE_UNREGISTERED_RELATION_TYPES.get(
                str(row.get("relation") or "")
            )
            if (
                allowed_types is None
                or str(row.get("value_type") or "") not in allowed_types
            ):
                raise RuntimeError(                          # ② 여기서 즉시 abstain
                    f"unregistered_live_relation:{row.get('relation')}"
                )
            normalized.append(row)
            continue
        ...
```

- `relation_contract()`는 `RELATION_CONTRACTS`(`claim_contract_relation_registry.py`)에서
  **정확한 relation 이름 문자열**로 조회합니다. 이 딕셔너리는 **73개** 항목이며, 전부
  그동안 typed_evidence_ref 평가 문항을 수작업으로 만들면서 나온 이름들입니다
  (`entry_fame`조차 이 73개 안에 없습니다).
- 등록 안 된 relation은 `_SAFE_UNREGISTERED_RELATION_TYPES`(**6개**: `entry_fame`,
  `entry_reputation`, `included_items`, `published_at`, `trade_status`,
  `enhancement_probability`)에 있어야만 통과합니다.
- 둘 다 아니면 **즉시 `RuntimeError`** → `answer()`의 바깥 `except`가 잡아서
  **abstain**으로 나갑니다. 코퍼스에 근거가 있는지 없는지는 전혀 안 봅니다.
- 즉 Qwen 플래너가 자유질문에서 뽑아낸 relation 이름이 이 **79개 목록** 안에
  없으면 무조건 실패합니다. "디레지에 난이도"는 relation이 아마
  `difficulty_types`류일 텐데 79개 안에 없어서 100% 실패합니다.
- `if "강화" in question and "확률" in question:`은 정확히 이 프로젝트가 금지해온
  "개별 실패 질문에 맞춘 수작업 규칙"입니다.

---

## 2. RELATION_CONTRACTS의 실제 구조 — family가 핵심 단위

`claim_contract_relation_registry.py`를 보면 각 relation은 사실 **이름 자체가
아니라 family(11종)**에 묶여 있습니다:

```
family                  -> allowed_value_types                  validation_mode
quantity_limit          -> entity_list, number                  typed_family
percentage_effect       -> percentage                            typed_family
boolean_state           -> boolean                               typed_family
temporal                -> date, date_range, datetime, ...       typed_family
trade_status            -> boolean, enum                         typed_family
price_currency          -> currency, number, price               typed_family
item_content            -> entity, entity_list                   typed_family
channel_location_method -> boolean, entity_list, enum, text       audit_only
effect_change           -> enum, text                             audit_only
policy_rule             -> text                                   audit_only
domain_property         -> enum, text                             audit_only
```

`validation_mode`가 `typed_family`인 7개 family는 이번 세션에 고친
`value_normalization.py`의 통화/불리언 정규화 같은 **타입 레벨 검증**과 연결돼
있고, `audit_only`인 4개 family는 인용 근거 존재 여부만 확인하는 가벼운 모드입니다.

**핵심 통찰**: relation 이름 73개를 하나하나 등록한 게 아니라, 애초에 **value_type
조합이 family를 거의 결정**합니다(`percentage`→`percentage_effect`,
`boolean`→`boolean_state`, `currency/price`→`price_currency`,
날짜류→`temporal` 등). 모호한 값 타입(`text`, `enum` 단독)만 여러 family에 걸쳐
있습니다.

---

## 3. 수정 방향 — 이름 등록 대신 value_type→family 라우팅

**절대 "게이트를 없애서 아무 relation이나 통과시키자"가 아닙니다.** 지금의
fail-closed 안전성은 유지하되, 게이트의 **키를 relation 이름에서 value_type/family
조합으로 바꾸는** 것이 목표입니다.

제안하는 로직 (정확한 구현 형태는 Codex 판단):

1. `relation_contract(row)`가 이름으로 못 찾으면, **바로 거절하지 말고**
   `row["value_type"]`이 어느 `typed_family`에 속하는지 확인합니다.
   - `value_type`이 하나의 `typed_family`에만 속하면(예: `percentage`→
     `percentage_effect` 하나뿐) 그 family의 `validation_mode="typed_family"`를
     그대로 적용하는 **synthetic contract**를 만들어 통과시킵니다.
   - `value_type`이 여러 family에 걸쳐 모호하면(`text`, `enum`, `entity_list`,
     `number` 단독) `audit_only` family로 라우팅합니다 — 인용 근거 존재만
     요구하고 구조적 family 검증은 생략. (이미 `audit_only`가 24개 relation에
     쓰이고 있는 기존 경로이므로 새로 만드는 게 아니라 재사용입니다.)
   - 이렇게 해도 여전히 매칭이 안 되는 경우(예: `value_type`이 정의된 14종
     `ValueType` Literal 밖)에만 지금처럼 `RuntimeError`로 거절.
2. `_SAFE_UNREGISTERED_RELATION_TYPES`(6개 수작업 목록)는 이 라우팅으로 흡수되어
   더 이상 필요 없어집니다 — 지우거나, 최소한 새 이름을 추가할 필요가 없어짐을
   확인.
3. `if "강화" in question and "확률" in question:` 키워드 하드코딩 제거. Qwen
   플래너의 시스템 프롬프트가 이미 "가격/비용은 value_type=currency" 같은 규칙을
   주고 있으니, `value_type=percentage`만 잘 뽑으면 이름과 무관하게 통과되어야
   합니다. 만약 Qwen이 `value_type=percentage`를 못 뽑는 게 실제 문제라면, 그건
   프롬프트 개선 대상이지 질문 키워드 하드코딩 대상이 아닙니다.

---

## 4. 확인이 필요한 부분 (구현 전 Codex가 먼저 봐야 할 것)

`resolve_requirement_claim_contracts` / `verify_minimal_claim_batch`
(`minimal_claim_verifier.py`)가 `contract.family` / `contract.validation_mode`를
어떻게 소비하는지 제가 끝까지 추적하지 못했습니다. synthetic contract를 만들 때:

- `RelationContract` dataclass의 다른 필드(`parent_relation`,
  `canonical_value_type`)가 하위 검증에서 실제로 쓰이는지, 쓰인다면 synthetic
  contract에 어떤 값을 넣어야 안전한지 확인 필요.
- `audit_only` 모드로 라우팅된 row가 하위 검증기에서 정말로 "인용 근거 있으면
  통과"로만 처리되는지, 아니면 다른 family-specific 로직이 암묵적으로 실행되는지
  확인 필요.

---

## 5. 하지 말 것

- relation 게이트를 완전히 제거해 아무 값이나 통과시키기 (fail-closed 원칙 위반).
- 새로 실패하는 질문마다 `_SAFE_UNREGISTERED_RELATION_TYPES`에 이름을 하나씩
  추가하는 임시방편 (지금 방식의 연장선일 뿐, 근본 수정 아님).
- `if "강화" in question...` 같은 질문 키워드 하드코딩을 다른 실패 사례에도
  추가하기.
- 이 수정과 동시에 retrieval·표 구조화(Arm 1)·프롬프트를 같이 바꾸기 (효과 분리
  불가 — 이번은 relation 게이트만).

---

## 6. 검증 계획

- 회귀 확인: 기존 sealed64 / new_claim32(adaptive) / untouched32 세트에서
  현재 통과하던 79개 relation 기반 문항들이 여전히 통과하는지.
- 신규 확인: "디레지에 난이도 뭐뭐있어"류, 79개 목록에 없는 relation이 나올
  자유질문 여러 개로 abstain이 사라지는지 (단, 오답이 새로 통과하지 않는지도
  같이 확인 — audit_only 라우팅이 근거 없는 답을 흘려보내지 않는지가 핵심).
- 단위 테스트 추가: value_type이 `typed_family`에 명확히 속하는 경우 /
  모호해서 `audit_only`로 가는 경우 / 14종 `ValueType` 밖이라 여전히 거절되는
  경우, 세 가지를 각각 재현.

---

## 7. 수정 후 내가(Claude) 재검증할 것

- [ ] `_SAFE_UNREGISTERED_RELATION_TYPES`와 `"강화"/"확률"` 키워드 하드코딩 제거 확인
- [ ] value_type→family 라우팅이 실제로 이름 미등록 relation을 통과시키는지 코드로 재현
- [ ] 기존 sealed/adaptive 세트에서 회귀 없음
- [ ] "디레지에 난이도" 등 신규 자유질문이 abstain을 벗어나는지, 그리고 근거 없는
      오답이 새로 노출되지 않는지 둘 다 확인
- [ ] audit_only 라우팅 경로가 인용 근거 요구를 그대로 유지하는지 확인
