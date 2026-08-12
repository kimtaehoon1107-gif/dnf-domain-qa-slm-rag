# 지시서 — claim evidence_ref 최소성 라운드 마무리

작성: 2026-08-12 (개정)
Qwen 호출 예산: **0회.** 데모 10번 라이브 재확인은 이미 완료됐다(아래 참고).

P0(조사)·P1(설계)·P2(구현+회귀)·P3(sealed 재채점+adaptive 32+데모 10번
라이브 재확인)는 전부 끝났다. 이 지시서는 **커밋과 문서 반영만** 다룬다.
새로 조사하거나 설계를 바꾸지 않는다.

---

## 1. 데모 10번 라이브 재확인 — 완료됨 (재실행 금지)

별도로 직접 확인 완료. `reports/v3/claim_evidence_ref_minimality_p3_20260812.md`
"데모 10번" 절에 전체 과정이 기록돼 있다. 요약:

```
결과        evidence_refs 6개 그대로 (축소되지 않음)
원인        _claim_evidence_surface_coverage 가드가 정상 작동 —
            시작일(8월 6일)이 어느 근거의 본문에도 없어서
            단일 근거로 줄이면 정보 손실이 생기므로 거부함
판정        P2 결함 아님. 정확한 최소 근거는 부분집합({E1,E3})이지
            단일 근거가 아니며, 부분집합 최소화는 이번 범위 밖(P1에서
            의도적으로 제외)
```

**이 항목을 다시 실행하지 말 것 — Qwen 낭비다.** 이미 결론 났다.

---

## 2. 커밋 (2개 그룹)

**하지 말 것: `app/ui/chat_preview.html`을 이 커밋들에 절대 포함하지 말 것.**
그건 이번 라운드와 무관한 별도 변경이고 아직 커밋 여부가 따로 결정 중이다.

### 그룹 1 — 코드 + 테스트

```
src/v3/product_minimal_verifier.py
tests/v3/test_product_free_rag.py
```

커밋 메시지 예시: `fix: minimize claim citations to a single sufficient evidence ref`

### 그룹 2 — 조사·검증 기록

```
docs/v3/claim_evidence_ref_minimality_plan.md
docs/v3/claim_evidence_ref_minimality_closeout_plan.md   (이 파일)
reports/v3/claim_evidence_ref_minimality_survey_20260812.json
reports/v3/claim_evidence_ref_minimality_p3_20260812.md   (1번 결과 반영본)
reports/v3/claim_evidence_ref_minimality_a6_saved_rescore_20260812.jsonl
reports/v3/claim_evidence_ref_minimality_a6_adaptive_replay_20260812.jsonl
```

커밋 메시지 예시: `docs: record claim evidence-ref minimality investigation and P3 verification`

### 게이트

- [ ] `git add .` 사용 안 함 — 파일 하나씩 지정
- [ ] `app/ui/` 무포함
- [ ] 커밋 후 `git status`로 의도한 파일만 반영됐는지 확인

---

## 3. 문서에 한계 두 줄 남기기

P3에서 나온 사실 두 가지는 벤치마크가 아니지만, 기록 안 하면 나중에 아무도
이유를 모른다.

`PORTFOLIO.md` §12(한계와 운영 계획)에 아래 취지로 **두 문단**을 추가한다.
**표현은 자유롭게 다듬되, 숫자는 이번 P3 보고서 값 그대로 쓸 것.**

```
(1) adaptive 세트 재보정 필요
adaptive-32 평가 세트는 2026-08-10 코퍼스 기준으로 만들어졌다. 이후 코퍼스가
갱신되면서(chunk SHA 변경) 같은 세트를 재실행하면 mode가 19/32 바뀐다
(대부분 answer→unsupported). 자동 채점기의 정답 chunk ID 목록도 옛 코퍼스
기준이라 이번 실행에서 자동 0/32가 나왔는데, 이는 정확도 저하가 아니라
채점 기준 자체가 낡았다는 뜻이다. adaptive 세트와 채점기를 코퍼스 갱신에
맞춰 재보정하는 일은 별도 라운드로 남겨둔다.

(2) claim 근거 최소화는 단일 근거 사례만 처리한다
claim당 근거를 줄이는 기능은 "근거 하나로 전체 claim이 증명될 때"만
작동한다. 여러 근거의 부분집합이 함께 필요한 경우(예: 시작일은 문서
제목에만, 종료일은 본문 한 곳에만 있는 경우)는 이번 범위에서 제외했다 —
잘못 줄이면 답의 근거 문장에서 정보가 사라지는 위험이 더 크기 때문이다.
부분집합 최소화는 별도 라운드로 남겨둔다.
```

`README.md`에 adaptive 24/32 같은 옛 수치를 인용하는 곳이 있다면, "다른
코퍼스 스냅샷 기준"이라는 각주를 붙인다. **숫자 자체를 새로 바꾸지 말 것**
— 8/10 코퍼스 기준 24/32는 그 시점 기준으로는 여전히 유효한 값이다.

### 게이트

- [ ] PORTFOLIO.md §12에 위 두 사실이 숫자와 함께 들어갔다
- [ ] 기존 sealed 수치(20/32, 37/64)는 손대지 않았다
- [ ] adaptive 24/32 수치 자체를 지우거나 고치지 않았다 — 맥락만 덧붙였다

---

## 4. 하지 말 것

- 동일 fingerprint adaptive 32문항 재실행 (예산 밖 — 별도 승인 필요)
- 자동 채점기의 accepted-chunk-ID 목록 갱신 착수 (범위 밖 — 별도 라운드)
- sealed A6 저장 출력 재실행·수정
- `app/ui/` 수정
- `git add .`

---

## 5. 보고 양식

```markdown
## 2. 커밋
- 그룹1 커밋 해시:
- 그룹2 커밋 해시:
- git status 확인 결과 (의도한 파일만 반영됐는가):

## 3. 문서
- PORTFOLIO.md §12 추가 내용 (두 문단):
- README.md 각주 추가 여부:
```

---

## 6. 이 라운드가 끝나는 조건

2번 커밋 완료 + 3번 문서 반영이면 **claim evidence_ref 최소성 라운드는
종료**다. adaptive 세트 재보정과 부분집합 최소화는 각각 별도 지시서로
다룬다(원하면 다음에 요청).
