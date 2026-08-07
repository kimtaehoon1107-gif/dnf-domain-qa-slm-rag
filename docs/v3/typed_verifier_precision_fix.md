# 지시서 — typed evidence-ref 검증기 정밀도 수정 (형식 매핑 버그 3종)

작성: 2026-07-24 · 대상: Codex · 상태: 진단 완료, 수정 요청
대상 파일: `src/v3/typed_evidence_ref.py`

---

## 0. 규율 — 봉인 홀드아웃 재실행 금지

이 수정의 검증은 **frozen-95 / adaptive-32** 에서만. 봉인된 64문항
(`typed_evidence_ref_generalization_64_sealed_e56780c8…`)에 **재실행하면 홀드아웃이 파괴**됩니다.
64문항의 57.8%는 현재 파이프라인 버전의 영구 기록입니다. 수정본은 나중에 **새 홀드아웃**에서만
최종 측정합니다.

---

## 1. 배경

봉인 홀드아웃 1회 실행 결과 `gold_value_complete 37/64 = 57.8%`. 실패 분해에서
`verifier_overreject` 14건 중 약 10건이 **모델이 정답 값을 냈는데 런타임 검증기가 거절**한
경우였습니다. Claude가 검증기 코드를 열어 재현으로 근본 원인 3종을 확정했습니다.

핵심: **채점기의 정규화 계약(9규칙)은 통화/불리언을 정규화하지만, 런타임 검증기
(`typed_evidence_ref.py`)는 그 정규화를 공유하지 않습니다.** 검증기가 먼저 답을 죽여서
채점기가 볼 답 자체가 사라집니다.

---

## 2. 버그 3종 (전부 재현 확인)

### 버그 ① 통화: 맨 숫자에 단위가 없으면 항상 실패
`_value_supported`(≈577) currency 분기:
```python
if value_type in {"price", "currency"}:
    model_values = _currency_values(str(value))
    return bool(model_values) and model_values <= _currency_values(evidence_text)
```
`_currency_values`(≈456)의 정규식은 `숫자 + (만/억) + 단위`가 **인접**해야 값을 뽑습니다.
그런데 모델은 통화 값을 **단위 없는 숫자**로 냅니다:
```
slot 52: value=22600 (int)    -> _currency_values('22600') = ∅  -> False (오거절)
slot 53: value='12900' (str)  -> ∅  -> False
slot 54: value='10' (str)     -> ∅  -> False
```
근거 텍스트에는 `12,900 세라`가 있어 `{(12900,'SERA')}`가 정상 추출됩니다. 문제는
**모델 값 쪽**입니다. 검증기가 "모델이 낸 amount가 근거의 amount 집합에 있는가"를 봐야 하는데,
모델 값에서 단위를 요구해 ∅이 됩니다.

### 버그 ② 통화: 비표준 단위 미인식
정규식 단위가 `세라|골드|원|SERA|GOLD|KRW`뿐입니다. 게임 내 재화가 빠졌습니다:
```
_currency_values('광휘의 잔영 120개') = ∅   (slot 12)
_currency_values('1500 마일리지')     = ∅
'골드 코인'은 '골드'만 부분매칭되어 단위가 GOLD로 잘못 잡힘  (slot 54)
```
누락 단위: `광휘의 잔영, 마일리지, 골드 코인, 코인, 포인트, 세라 코인` 등.
`_CURRENCY_UNITS` 매핑과 정규식 둘 다 확장 필요.

### 버그 ③ boolean: 증거 마커 목록이 불완전하고 방향이 틀릴 수 있음
`_boolean_evidence`(≈539)가 긍정/부정을 고정 문자열 마커로 판별합니다.
```
긍정 마커: 적용됩니다, 포함됩니다, 계산됩니다, 가능합니다
부정 마커: 않, 미적용, 제외, 계산되지, 불가, 없
```
누락으로 인한 오거절:
```
slot 10 근거 "…현상이 수정됩니다." -> _boolean_evidence = ∅  (수정됩니다 미등록)
slot 58 근거 "거래타입 교환가능"     -> ∅               (교환가능 미등록)
```
**더 위험한 것 — 방향 오판(slot 35):**
```
근거 "다른 계정으로의 이동이 발생하면 교환불가 타입으로 변경" (정답 True)
_boolean_evidence = {False}   ← "교환불가"의 "불가"가 부정 마커에 걸려 False로 뽑힘
```
여기서 "불가"는 상태 이름(교환**불가**)의 일부이지 문장의 부정이 아닙니다. 단순 substring
매칭이라 방향을 거꾸로 뽑습니다. **마커를 추가만 하면 이 방향 오판이 악화될 수 있으니,
substring이 아니라 관계(relation) 문맥을 반영한 판정이 필요**합니다.

---

## 3. 수정 방향 — 검증된 참조 구현

아래 프로토타입은 Claude가 실제 실패/안전 케이스에 돌려 검증했습니다. Codex는 이 로직을
`typed_evidence_ref.py`에 반영하되, 최종 구현 형태는 판단해도 됩니다. **단 아래 검증표의
입출력은 반드시 재현되어야 합니다.**

### ② 통화 — 단위 사전 확장 (①의 전제이므로 먼저)
`_currency_values`의 단위 정규식/사전에 게임 재화를 추가하고 **긴 단위를 먼저 매칭**
("골드 코인"이 "골드"로 부분매칭되지 않도록).

```python
_UNITS_EXT = ['광휘의 잔영','골드 코인','세라 코인','마일리지','포인트','코인',
              '세라','골드','원','SERA','GOLD','KRW']   # 긴 것 우선
unit_alt = '|'.join(re.escape(u) for u in _UNITS_EXT)
pat = re.compile(rf'(\d[\d,]*(?:\.\d+)?)\s*(만|억)?\s*({unit_alt})', re.IGNORECASE)
```
검증: `"10 골드 코인"→{(10,'골드 코인')}`, `"1500 마일리지"→{(1500,'마일리지')}`,
`"12,900 세라"→{(12900,'세라')}`.

**남은 sub-요건:** `광휘의 잔영 120개`는 `단위+숫자+개` 형식(number+unit 아님)이라 위 정규식으로
안 잡힙니다. `(?P<unit>광휘의 잔영|...)\s*(?P<amount>\d[\d,]*)\s*개` 같은 **역순 패턴**도
추가해 amount=120으로 인식할 것.

### ① 통화 — amount 비교 (단위는 인용 근거가 보증)
모델은 통화를 **단위 없는 숫자**로 냅니다(`22600`(int)/`'12900'`(str)). 현재 코드는
`_currency_values(str(value))`로 단위를 요구해 항상 ∅ → 거절. amount끼리 비교로 교체:

```python
def _amount_of(value):
    m = re.search(r'(\d[\d,]*(?:\.\d+)?)\s*(만|억)?', str(value))
    if not m: return None
    return int(float(m.group(1).replace(',','')) * {'만':10000,'억':100000000}.get(m.group(2),1))

# currency 분기:
model_amt = _amount_of(value)
evidence_amounts = {amt for amt,_ in _currency_values(evidence_text)}   # 확장된 값
return model_amt is not None and model_amt in evidence_amounts
```
**안전성:** amount를 **모델이 인용한 그 근거**의 amount 집합과 대조하므로, 그 금액이 근거에
없으면 여전히 거절. 인용 근거의 단위가 곧 정답 단위이므로 별도 단위 필드는 불필요.

검증표:
```
모델 '12900' + 근거 "12,900 세라"        -> True   (slot 53 복구)
모델 22600  + 근거 "22,600 세라"         -> True   (slot 52)
모델 '10'   + 근거 "10 골드 코인"          -> True   (slot 54)
모델 '12900'+ 근거 "99,999 골드"(금액없음) -> False  (★ 안전: 계속 거절)
```

### ③ boolean — 부정 우선 + 상태명사 보호 (가장 주의)
`_boolean_evidence`를 **substring OR 집합**에서 **부정 우선·배타** 판정으로 교체.
"교환불가/거래불가"의 "불가"를 문장 부정으로 오인하지 않도록 상태명사를 먼저 가림.

```python
POS = ['수정','개선','추가','변경','적용','포함','계산됩니다','가능','교환가능']
NEG_ACTION = re.compile(r'(되지\s*않|하지\s*않|지\s*않습니다|불가능|미적용|제외됩니다|계산되지)')
STATE_NOUN = re.compile(r'(교환불가|거래불가|환불불가|사용불가|합성불가)')

def _boolean_evidence(text):
    masked = STATE_NOUN.sub('___', text)   # 상태명사의 '불가'를 부정 판정에서 제외
    if NEG_ACTION.search(masked):          # 동작 부정이 있으면 False (배타)
        return {False}
    if any(p in text for p in POS):
        return {True}
    return set()
```

검증표 (7/7 통과 확인):
```
"…현상이 수정됩니다."                    -> {True}   slot10 복구
"거래타입 교환가능"                       -> {True}   slot58 복구
"…교환불가 타입으로 변경"                 -> {True}   ★slot35 방향 정상
"…교환불가 상태로 변경되지 않습니다"       -> {False}  slot35 반대쌍
"…연출이 출력되지 않는 현상"              -> {False}  ★slot2 계속 막힘
"결투장에서는 적용되지 않습니다"           -> {False}  slot18 유지
"정지된 이후에도 OTP 이용이 가능합니다"    -> {True}   slot34
```
**POS에 '변경'(맨) 포함이 핵심**: slot35 True는 "변경**됩니다**"가 아니라 "변경"뿐. 다만
"변경되지 않습니다"는 NEG_ACTION이 먼저 잡아 False가 되므로(배타) 충돌 없음.

### 공유 — 중복 구현 금지
가능하면 검증기와 채점기(`score_typed_evidence_ref_generalization.py`)의 통화/불리언
정규화가 **같은 함수를 공유**하도록. 지금 둘이 갈라져서 채점기 정규화가 검증기에 반영 안 됨.

---

## 4. 검증 (frozen-95 / adaptive-32 에서만)

- 수정 전후로 이 세 유형(currency/boolean)의 오거절이 실제로 줄고, **틀린 답이 새로
  통과되지 않는지**(특히 ③ 방향 오판) 대조.
- adaptive-32 typed arm 재채점으로 currency/boolean 오거절 감소분 측정.
- 단위 테스트 추가: 버그 3종 각각의 재현 케이스 + slot 35 방향 유지 케이스.
- **봉인 64에는 절대 재실행 금지.**

---

## 5. 실행 후 내가(Claude) 재검증할 것
- [ ] 세 버그 재현 케이스가 수정 후 통과
- [ ] slot 35 방향(교환불가로 변경 = True)이 올바르게 유지
- [ ] amount-only 매칭이 단위 다른 오답을 여전히 막는지
- [ ] 검증기·채점기 통화 정규화가 공유되는지(중복 제거)
- [ ] frozen-95에서 안전(fail-closed) 손실 없이 오거절만 감소

---

## 6. 하지 말 것
- 통화/불리언을 무조건 통과시키는 느슨화 (틀린 답 유입). 이번 홀드아웃에서 검증기가
  옳게 막은 boolean 방향 오류(slot 2), 날짜 오류(slot 9)는 **계속 막아야** 합니다.
- 봉인 64 재실행.
- retrieval·프롬프트 동시 변경 (효과 분리 불가). 이번은 검증기 형식 매핑만.
