# 지시서 — 64문항 slot 25 교체 (temporal_role 난이도 강화)

작성: 2026-07-24 · 대상: Codex · 사용자 승인: "교체하자 slot 5처럼 여러 시점 있는걸로"
원본: `data/review/typed_evidence_ref_generalization_candidate_64.jsonl`

---

## 1. 왜 교체하나

기존 slot 25는 "트레이드 가이드는 언제 업데이트됐어?" → `2026-01-05`.
정답값 자체는 원문에 정확하나, **문서 편집일(웹 관리 메타데이터)**이라 두 가지 문제:

- 나머지 63개는 게임 사실인데 25번만 문서 관리 정보 (범위 이질)
- 그 문서에 날짜가 **1개뿐**이라 `temporal_role`의 핵심 — **여러 시점 중 맞는 역할 고르기**
  — 를 전혀 테스트하지 못함 (slot 5가 적용일↔다운로드일을 구별해야 했던 것과 대조)

**"봉인 코퍼스에선 유동값이 아니다"는 내(Claude) 지적은 철회했습니다** — 재현성 문제는 없습니다.
남은 유일한 이유는 **temporal_role 난이도 부재**입니다.

---

## 2. 교체 대상 문서 — 확인 완료

던파ON 포인트 교환소 가이드. **서로 다른 역할의 초기화 시점이 4종** 있어 slot 5 수준의
역할 구별을 요구합니다.

```
document_id : document_sha256_b7bc843187a068ea6f4781b051c77e872a203cbe726dd21f09b10ce9e52e0c25
source_id   : dnf_game_guide (유지)
```

원문 (바이트 확인된 문장, 각각 별도 청크):

```
chunk_sha256_6e8d119c… :
  "- 1일 기준은 오전 6시~ 다음 날 오전 6시 / 1주 기준은 매주 목요일 오전 6시 / 1월 기준은 매월 1일 오전 6시"

chunk_sha256_ecbd4804… :
  "출석체크는 매일 06시를 기준으로 갱신됩니다."
```

**핵심:** 일일/주간/월간 세 초기화 기준이 나란히 있습니다. 모델이 "주간 기준"을 물으면
**일일(매일 6시)·월간(매월 1일)과 혼동하지 않고 "매주 목요일"을 골라야** 합니다.
이게 temporal_role이 테스트하려는 바로 그 역할 구별입니다.

---

## 3. 제안 문항 (Codex가 정확 좌표로 작성)

두 요구를 두어 역할 구별을 강제하세요.

```
질문(예): 던파ON 출석체크에서 하루는 언제를 기준으로 갱신되고, 주간 초기화는 무슨 요일이야?

요구 1  relation: daily_reset_time    value_type: datetime/time
        정답: 오전 6시 (매일 06시 기준)
        근거: "출석체크는 매일 06시를 기준으로 갱신됩니다."  또는  "1일 기준은 오전 6시~"

요구 2  relation: weekly_reset_day    value_type: enum/text
        정답: 매주 목요일
        근거: "1주 기준은 매주 목요일 오전 6시"
```

정확한 relation/value_type/좌표는 Codex 판단으로 확정하되, **두 요구의 시점 역할이 서로 달라야**
합니다(일일 vs 주간). 필요하면 월간(매월 1일)을 세 번째 요구나 오답 유도용으로 활용 가능.

---

## 4. 제약 — 반드시 유지

- `slot_ordinal: 25`, `source_id: dnf_game_guide`, `primary_dimension: temporal_role` 유지
  (8×8 균형·유형 배분 불변)
- 근거 좌표 `body[start:end] == text` 바이트 일치
- 기존 165 + 나머지 63문항과 질문 exact overlap 0
- `execution_allowed: False`, `training_allowed: False` 잠금 유지
- `author_status`: `draft_complete_pending_human_review`
- 나머지 63문항 손대지 말 것 (slot 25만 변경)

---

## 5. 교체 후 내가 재검증할 항목

- [ ] slot 25 근거 좌표 바이트 일치
- [ ] 두(이상) 요구의 시점 역할이 서로 다름 (일일/주간 등)
- [ ] 정답값이 실제로 여러 시점 중 "질문이 지목한 역할"의 값임
- [ ] 질문 exact overlap 0
- [ ] 8×8 균형 불변, 나머지 63문항 미변경

---

## 6. 진행 상태 참고

64문항 사람 감수 진행 중. 1~3묶음(dnf_notice·update·event, slot 1~24) 통과.
4묶음(dnf_game_guide) 중 slot 26~32는 확인 완료, slot 25만 이 교체 대기.
5묶음 이후(dnf_faq·account_policy·seria_shop·monthly_item, slot 33~64)는 감수 예정.
