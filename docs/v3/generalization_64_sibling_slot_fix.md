# 지시서 — 64문항 초안의 sibling 슬롯 2건 교체 (slot 3, 19)

작성: 2026-07-24 · 대상: Codex · 상태: 감수 후 수정 요청 (사용자 승인: "a로 다른거하자")
원본: `data/review/typed_evidence_ref_generalization_candidate_64.jsonl`

---

## 1. 독립 검증 결과 — 초안은 거의 완벽

64문항 전체를 코드로 재검증했습니다. Codex 주장 전부 사실 확인:

- 근거 좌표 89/89 `body[start:end] == evidence_text` 정확 일치
- unsupported 요구 8개, 내부 질문 중복 0, 기존 165문항과 exact overlap 0
- 8 dimension × 8 source 완전 균등

기계 스캔에서 나온 20개 플래그 중 **18개는 제 스캐너 오탐**이었습니다
(ISO 날짜·만단위 정규화를 스캐너가 몰라서 — 원문엔 `5월 28일`, `4,000만 골드`로 다 존재).

**실제 수정 대상은 아래 2건뿐입니다.**

---

## 2. 문제 — sibling 값이 동일해 변별 불가

`sibling_relation` dimension의 목적은 **모델이 형제 행을 구별하는지** 테스트하는 것입니다.
그런데 두 슬롯은 형제의 값이 같아, **모델이 틀린 행을 골라도 정답으로 통과**합니다.

```
[slot 3] dnf_notice — 6/12 세리아 특별 상점
  [Event]종말의 계시 500개 상자 → sale_quantity = 2
  피로도 30 회복의 비약          → sale_quantity = 2      ← 둘 다 2

[slot 19] dnf_event — 2026 아라드 패스 웨딩
  웨딩 아바타 풀세트 상자 → deletion_at = 2026-08-13 06시
  웨딩 보너스 상자        → deletion_at = 2026-08-13 06시  ← 둘 다 동일
```

두 원본 문서를 직접 열어 확인했습니다. **데이터 오류가 아니라, 그 문서의 형제 값이 실제로
같은 것**입니다. 따라서 같은 문서로는 못 고치고 **다른 문서로 교체**해야 합니다.

---

## 3. 교체 기준 — 잘 만든 6개 슬롯이 정답 패턴

같은 dimension의 나머지 6개는 전부 형제 값이 다릅니다. 이걸 따르세요.

```
slot 51 [dnf_seria_shop]  상의 아바타 6,500세라 ↔ 상의 클론 아바타 2,600세라   ← 같은 문서, 다른 값
slot 27 [dnf_game_guide]  트레이드 기본 3% ↔ 장비 추가 수수료 2%
slot 35 [dnf_faq]         동일 계정 이동 False ↔ 다른 계정 이동 True
slot 11 [dnf_update]      메모리 '감소' ↔ '수정'
```

**핵심: 두 형제의 required_values가 서로 달라야 합니다.**

---

## 4. 제약 — 반드시 지킬 것

- **slot 3은 `dnf_notice`, slot 19는 `dnf_event`를 유지**하세요. 8×8 출처 균형(출처당 정확히 8개)이
  깨지면 안 됩니다.
- `primary_dimension`은 `sibling_relation` 유지.
- 근거 좌표는 `chunks_dnf_official_v3.1_bd0242b3…` 원문과 `body[start:end] == evidence_text`
  바이트 일치여야 함.
- 기존 165문항 + 나머지 62문항과 질문 exact overlap 0.
- `execution_allowed: False`, `training_allowed: False` 잠금 유지, `author_status`는 재작성이므로
  `draft_complete_pending_human_review`로 갱신.

---

## 5. 실현 가능성 — 이미 확인함 (불가능한 심부름 아님)

코퍼스를 검색해 교체 재료가 실재함을 확인했습니다.

- **dnf_notice**: 서로 다른 수량이 함께 나오는 청크 **11개** 존재
  (예: `[5주차] 20주년 선물 추첨` 문서에 `12개 / 4개`처럼 값이 다른 항목).
- **dnf_event**: 삭제일·수량·가격이 다른 형제를 가진 이벤트 문서가 다수.

Codex가 코퍼스에서 골라 작성하면 됩니다. 값이 다른 쌍만 확보되면 됩니다.

---

## 6. 완료 후 내가 재검증할 항목

교체본을 받으면 다음을 코드로 확인합니다. 미리 알려드립니다.

- [ ] slot 3, 19의 형제 `required_values`가 **서로 다름**
- [ ] 두 슬롯의 모든 근거 좌표가 원문과 바이트 일치
- [ ] 두 질문이 기존 165 + 나머지 62와 exact overlap 0
- [ ] 8×8 균형 불변 (dnf_notice 8, dnf_event 8, sibling_relation 8)
- [ ] 나머지 62문항은 손대지 않음 (해당 슬롯만 변경)

---

## 7. 이 수정이 사소해 보여도 중요한 이유

이 세션에서 **"값이 우연히 같아 틀린 답이 정답 처리되는"** 채점 함정을 여러 번 만났습니다
(frozen 95의 grounded 73 부풀림, false_full 오분류). sibling 슬롯의 값이 겹치면 **홀드아웃
세트가 바로 그 함정을 내장**하게 됩니다. 봉인 전에 잡아야 하는 이유입니다.

나머지 62문항은 GO입니다. 이 2건만 교체되면 64문항 전체가 봉인 감수 단계로 갈 수 있습니다.
