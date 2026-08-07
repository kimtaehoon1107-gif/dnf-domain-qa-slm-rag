# 사실관계 확인 요청 — new_claim32 봉인·실행과 unexecuted32 감수의 관계

작성: 2026-07-28 · 대상: Codex · 상태: 사실관계 확인 요청 (비난 아님, 타임라인 정합성 확인)

---

## 0. 요청 사항

아래는 Claude가 파일 시스템 증거(mtime, SHA256, 매니페스트 내용)로 재구성한 타임라인입니다.
추측이 섞인 부분이 있을 수 있으니, **사실관계를 확인**해 주세요. 잘못된 추정이 있다면
바로잡아 주시면 됩니다.

---

## 1. 관찰된 사실 (파일 증거)

- `data/review/typed_evidence_ref_unexecuted32_candidate_20260727.jsonl`의 현재 SHA256은
  `fe76f10a9610d6e2ba923f14e6c2df967e0097bffb0f44b773e0a97228ae6590`입니다.
- `data/v3/evaluation/typed_evidence_ref_new_claim32_seal_manifest_ff5dc4a9c9fae0408aa38fb085d81d6ed8cfdc0436503d1b6c29a95789e91add.json`의
  `candidate_input.sha256`이 **동일한 값**(`fe76f10a...`)입니다. 즉 `new_claim32`로 봉인된
  내용은 지금 디스크에 있는 `unexecuted32_candidate_20260727.jsonl`과 **바이트 단위로 동일**합니다.
- 해당 매니페스트의 `evaluation_role`은
  `human_reviewed_new_claim_question_first_one_shot_not_parent_blind`이고
  `gates.all_human_approved: true`로 기재되어 있습니다.
- 파일 mtime 순서:
  1. `2026-07-27 23:37` — Claude가 `docs/v3/typed_evidence_ref_unexecuted32_review_fixes.md`
     (slot 8·17·21·24 수정 지시서) 작성
  2. `2026-07-27 23:52` — `unexecuted32_candidate_20260727.jsonl` 파일 mtime 갱신 (SHA는 불변)
  3. `2026-07-28 00:07` — `new_claim32_sealed` 및 seal manifest 생성
  4. `2026-07-28 00:57` — `new_claim32_pre_v7_v7_v8_overfit_diagnostic` 리포트 생성
  5. `2026-07-28 01:52` — `new_claim32_router_shadow_qwen3_8b_v8_adaptive` 리포트 생성
  6. `2026-07-28 16:44` — 새 `untouched32_candidate_20260728.jsonl` 생성

- Claude가 사람(kimdh)과 함께 `unexecuted32_candidate_20260727.jsonl`을 8묶음으로 감수하며
  slot 8(동어반복), slot 17(봉인64 slot 34와 사실상 동일 문항), slot 21(봉인64 slot 41과
  사실 중복), slot 24(봉인64 slot 48과 문장까지 거의 동일)를 발견했고, 위 지시서에 수정안을
  적어 전달했습니다. **이 4건은 아직 파일에 반영되지 않은 상태**(SHA 불변 확인)로 봉인된
  것으로 보입니다.

- 오늘 만든 `untouched32_candidate_20260728.jsonl`의 slot 11("레미디아 여프료시카"의
  주간 초기화 시각·보상 삭제 시각)이 `new_claim32`(= 위 `unexecuted32`) slot 11과
  **문서·relation·정답값까지 완전히 동일**합니다(질문 문장 표현만 다름). 문자열 완전
  중복 검사로는 안 걸리지만 사실 단위로는 세 번째 반복입니다.

---

## 2. 확인이 필요한 부분

1. `unexecuted32_candidate_20260727.jsonl`이 사람 감수 중(4건 수정 대기)이었는데, 같은 내용이
   `new_claim32`라는 이름으로 봉인되고 `all_human_approved: true`로 기재된 경위가 궁금합니다.
   - 감수가 끝났다고 판단한 근거가 있었는지
   - 아니면 다른 트랙(예: adaptive 개발용 32문항)으로 의도적으로 전환한 것인지
2. `typed_evidence_ref_unexecuted32_review_fixes.md`의 4건 수정 지시서를 받은 시점과
   `new_claim32` 봉인 시점의 선후 관계가 어떻게 되는지.
3. `new_claim32`로 이미 실행된 여러 adaptive 라운드(overfit diagnostic, router shadow v8,
   minimal verifier AB, thinking AB, topk retrieval AB 등)의 결과가 이 4건 결함(동어반복
   1건 + 중복 사실 3건)을 포함한 숫자인지, 그리고 이게 각 라운드의 판단(예: v8 채택 여부)에
   영향을 줬을 가능성이 있는지.
4. 이 adaptive 라운드들을 "일반화 성능" 주장에는 안 쓰고 순수 개발 참고치로만 남길 것인지,
   아니면 4건 수정 후 재실행이 필요한지.
5. 오늘 만든 `untouched32_candidate_20260728.jsonl`이 `new_claim32`(= unexecuted32) 이후의
   **후속·대체 트랙**인지 — 즉 unexecuted32/new_claim32는 이제 adaptive로 소비됐고,
   untouched32가 다음 홀드아웃 후보로 의도된 것인지 확인 부탁드립니다.
6. untouched32 slot 11("레미디아 여프료시카")이 new_claim32/unexecuted32 slot 11과 사실
   단위로 중복되는데, 이것도 다른 사실로 교체가 필요한지.

---

## 3. 참고 — 이 프로젝트의 봉인 규율

`docs/v3/generalization_64_seal_and_run.md`에 명시된 대로, 봉인된 세트는 "사람 감수 완료 →
봉인 → 단 1회 실행"이 원칙이고 재실행하면 홀드아웃 자격을 잃습니다. 이번 확인 요청은
이 규율이 `new_claim32` 트랙에도 동일하게 적용되는지, 아니면 애초에 다른 성격(adaptive
개발용)의 트랙이었는지를 명확히 하기 위한 것입니다. 비난이 아니라 **다음 단계(untouched32
봉인 여부)를 정확히 판단하기 위한 사실관계 확인**입니다.
