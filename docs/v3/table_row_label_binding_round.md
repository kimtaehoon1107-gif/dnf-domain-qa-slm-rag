# 지시서 — 표 행 매칭을 `row.subject` 대신 `row.label`로

작성: 2026-07-23 · 대상: Codex · 상태: **수정 라운드 (사전 기준 등록됨)**

선행: [table_binding_zero_selection_investigation.md](table_binding_zero_selection_investigation.md)
진단 산출물: `table_binding_zero_selection_audit_ce3d5165…jsonl` / 보고서 `4d53a6ad…json`

---

## 1. 진단 확인 결과

Codex 진단의 모든 수치를 재계산해 일치를 확인했습니다. S1 4 / **S2 25** / S3 0 / S4 4,
S2 점수 `(0,0)` 20 · `(1,1)` 5, `row.subject` 중앙값 64자, S1이 runtime veto가 아님(33/33).

"`_surface_match_score`를 완화하면 긴 산문을 오선택할 위험이 크다", "조사 제거만 적용하는
수정은 위험하다" — **둘 다 동의합니다.** Kiwi가 살린다는 10건을 열어보니 실제로 캡션 산문에
매칭돼 **틀린 행**을 되살리고 있었습니다 (F3 절 참조).

## 2. 진단이 놓친 것 — 근본 기전과, 이미 존재하는 해법

### 왜 산문이 들어갔나

[build_table_atomic_facts.py:484](../../src/v3/build_table_atomic_facts.py#L484)

```python
subject = _normalized_label(" ".join([context_subject, *identity_values]))
                                      ↑ 표 캡션          ↑ 진짜 행 개체
```

`row.subject`는 **"캡션 + 개체"를 이어붙인 것**입니다. 캡션이 문장이면 그 표의 모든 행이
같은 문장을 앞에 답니다. 실제로 **같은 149자 blob이 12개 요구·8개 문항에서 최적 행**으로
뽑힙니다 — 길이만으로 무엇과도 겹치는 자석 행입니다. 캡션 길이는 129자, 228자까지 갑니다.

### 그런데 원자 개체는 런타임에 이미 있습니다

[assemble_table_group_answers.py:23](../../src/v3/assemble_table_group_answers.py#L23)이
캡션 접두사를 떼어 `row["label"]`로 이미 저장합니다.

```python
def _row_label(subject, table_subject):
    if table_subject and subject.startswith(table_subject):
        label = subject[len(table_subject):].strip()
        if label:
            return label
    return subject                      # 접두사 불일치 시 자동 폴백
```

전체 4,017 fact 중 **3,893건(96.9%)**에서 접두사 제거가 성립하고, 남는 값은 정확히 원자 개체입니다.

```
캡션[129자] -> '타인에게 불쾌감을 주는 게시물(일반)'
캡션[228자] -> '[단진의 특별 상점]순수한 황금 증폭서'
캡션[ 42자] -> '입장 인원'
```

**그런데 매칭은 `label`이 아니라 `subject`를 씁니다.**
[grounded_answer_generator.py:268](../../src/v3/grounded_answer_generator.py#L268)

```python
row_score = _surface_match_score(
    selection_surface,
    row.get("subject"),      # <- 캡션까지 포함된 오염된 문자열
)
```

**코퍼스 재빌드가 필요 없습니다. 동결 산출물도 그대로입니다.**

---

## 3. 이번 라운드에서 할 것

### F1 (필수) — 행 매칭 대상을 `label`로

`grounded_answer_generator.py`에서 행 개체를 읽는 지점을 `row["label"]`로 바꿉니다.
`_row_label`이 이미 폴백을 내장하므로 별도 예외 처리는 불필요합니다.

- L268 `row.get("subject")` → 행 라벨
- L288 부근 수량 한정자 검사 `candidate[2].get("subject")` → 같은 기준
- L359 `row_subject = str(row.get("subject") or subject)` — **사용자에게 보이는 출력 문자열**입니다.
  여기도 라벨로 바꿀지는 판단해서 근거와 함께 보고하세요. 매칭과 표시는 목적이 다릅니다.

`view.get("table_subject")`로 하는 **S1 표 점수는 건드리지 마세요.** 지금 veto가 아니고
정렬 보조 키로만 쓰입니다(진단 확인 완료).

### F2 (선택) — 캡션 정규화 불일치

빌드 쪽 `_context_subject`는 `비용|가격|판매가|판매 기간|판매기간|삭제일|유효기간|시행일`을 떼고,
런타임 `_table_subject`는 `비용|가격|판매가`만 뗍니다. 이 불일치가 접두사 실패 3.1%의 원인일 수
있습니다. **F1 측정이 끝난 뒤에 별도로** 재세요. 같이 넣으면 어느 쪽 효과인지 못 가립니다.

### F3 (다음 라운드로 예약) — Kiwi 조사 제거

**거부가 아니라 순서입니다.** F1 측정이 끝난 뒤 별도 라운드로 재세요. 근거:

진단 보고서는 Kiwi가 S2 실패 10건을 `becomes qualifying`으로 되살린다고 기록했습니다.
그 되살아난 행이 무엇인지 확인했습니다.

```
요구: 타인_결제수단_도용 · 첫_이용제한
  최적 행 subject(149자): [ 4-6 …계정 도용 시도가 감지되어 거래 제한이…   ← Kiwi가 여기 매칭
  그 행의 label  ( 20자): 타인에게 불쾌감을 주는 게시물(일반)              ← 실제 행 개체

요구: 사칭 행위 · 1차~4차 이용제한 조건
  → 최적 행이 똑같이 '타인에게 불쾌감을 주는 게시물(일반)'
```

**되살아난 행은 틀린 행입니다.** 결제수단 도용 질문에 "불쾌감을 주는 게시물" 행이 이깁니다.
149자 캡션 blob이 무엇과도 겹치기 때문이고, Kiwi는 그 겹침을 **더 잘** 만들어줍니다.
점수 상승 15건 중 **8건이 캡션 접두사가 붙은 행**이었습니다.

따라서:

1. **지금 재면 숫자가 무의미합니다.** 그 10건은 Kiwi의 *캡션 산문 매칭 능력*을 잰 것이고,
   F1이 캡션을 떼면 그 매칭 자체가 사라집니다.
2. **교란.** 매칭 대상(`subject`→`label`)과 매처(regex→Kiwi)를 동시에 바꾸면
   개선이든 악화든 원인을 못 가립니다.
3. 산문 span 랭킹에서는 이미 음성이었습니다(50.0% → 42.9%). 다만 그건 **다른 문제**이므로
   이것만으로 배제하지는 않습니다.

F1 이후 라벨은 `증폭 보호권` 같은 짧은 개체가 되고 여기엔 조사가 실제로 붙습니다.
**그때 재는 Kiwi 숫자는 의미가 있습니다.** 구현은 커밋 `243e636` 이전 이력에 있습니다
(`subject_surface_similarity.py`, 조사·어미·기호 태그 제거 + Jaccard).

### 하지 말 것

- `_surface_match_score` 임계값·로직 완화
- Kiwi 조사 제거를 **이번 라운드에** 넣기 (위 F3 참조)
- 검색·라우팅·planner·조립기 수정
- 동결 산출물 재생성

---

## 4. 사전 성공 기준 — 실행 전에 확정, 사후 변경 금지

기준선은 `a51ebdf` 시점의 A+B 측정값입니다 (보고서 `d539f68c`).

| 지표 | 기준선 | 통과 조건 |
|---|---:|---|
| gold 값 정확 | 22/44 (50.0%) | **24 이상 AND 52% 이상** |
| false_full | 7 | **7 이하** |
| overreject | 3 | 5 이하 |
| span_strict == grounded | 58 == 58 | 유지 |
| 표 값 선택 성공 요구 (33건 중) | 0 | **8 이상** |

마지막 줄이 이번 라운드의 직접 지표입니다. 나머지는 부작용 감시용입니다.
**하나라도 미달이면 되돌립니다.** 동률은 실패입니다.

측정:

```bash
python src/v3/evaluate_router_backbone_mixed_metrics.py --generation-ab \
  --generator-model qwen3:8b --device cuda \
  --assembler-cases data/v3/evidence/extractive_assembler_v3_chunk_diverse_value_first_cases_e2991cc1237e706c3ff02dfb74f9c3a93e107fbee9a4ad9c0ac4e928c9e4ff88.jsonl
```

---

## 5. 절차

1. 수정 **전에** 동결 조립기 재현 확인
   (`06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c`)
2. F1 구현 + 단위 테스트 (캡션 오염 행이 원자 행에 밀리는 케이스 1건 이상)
3. 진단 스크립트 재실행 → 33요구의 `failed_stage` 재분포 기록
4. 95문항 A/B 측정
5. 4장 기준으로 판정. 미달이면 되돌리고 음성 결과를 보고서로 남길 것

---

## 6. 방법론 — 이 세션에서 실제로 당한 것

- **격리 프로브로 방향을 정하지 마세요.** 조사 제거는 4건 프로브에서 0/4 → 2/4였는데,
  그 4건을 실패 사례에서 골랐기 때문에 순효과와 무관했습니다. 전체 95에서는 50.0% → 42.9%로
  나빠졌습니다.
- **부분 개선을 성공으로 읽지 마세요.** 값-우선 선택은 overreject를 10 → 3으로 줄였지만
  false_full을 4 → 7로 늘렸습니다. 자기 기준 미달이라 켜지 않았습니다.
- 이번 라운드는 **직접 지표(표 값 선택 8건 이상)**가 있으니 부분 개선 논쟁을 피할 수 있습니다.

이 세션의 라운드 전적: **1승 3패**. 유일한 승리(A, value-shape 버그 수정)는
"명백한 버그를 고쳤고 부작용이 0"인 경우였습니다. F1도 같은 성격입니다 —
**오염된 문자열 대신 이미 계산된 깨끗한 문자열을 쓰는 것**이지, 새 휴리스틱이 아닙니다.
