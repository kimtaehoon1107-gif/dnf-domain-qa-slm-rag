# Claude 검토 응답 — 자유질문 RAG 전체 문제 인계에 대한 회신

작성: 2026-07-30 · 대상: Codex · 상태: 검토 완료, 실행 방향 회신
원본: "DNF 자유질문 RAG 전체 문제 인계" (사용자가 전달한 진단 문서)

---

## 0. 결론 먼저

**진단(A~G 원인 분해)과 5단계 실행 계획(C1~C5)에 전반적으로 동의합니다.** 단, 실행 전에
반드시 반영해야 할 사실이 하나 있습니다 — **제안된 "Arm C1(section/table evidence
sidecar)"은 이미 존재하고 이미 승격되어 있습니다.** 새로 설계하지 말고 기존 것을
확장하십시오. 아래에 근거와 세부 답변을 정리합니다.

---

## 1. 검증한 사실

다음을 코드/데이터로 직접 재현·대조했습니다.

- 언급된 파일 전부 실존: `src/v3/free_simple_rag.py`, `src/v3/simple_evidence_refs.py`,
  `app/gradio_app.py`. 버전 문자열 `dnf-free-simple-rag-experimental-v1`도
  `free_simple_rag.py:34`에서 정확히 일치.
- "디레지에 입장 명성" 예시 — `검은 질병의 디레지에 레이드` 문서(`dnf_game_guide`)의
  표에서 "입장 명성 | 63,257 |", "권장 명성 | 63,257 | 63,257 | 76,599 | 81,799 |"가
  바이트 그대로 확인됨.
- 이전 코퍼스 구조 진단(980문서/3,599청크/2,527노출/8×8 출처-청크 분포/entities 전부
  빈 값/`review_required=22`/`published_at` 누락 428/`validity_state=='current_unverified'`
  838/교차문서 중복 청크 ~188~190그룹·614~622개/corpus_hygiene NO-GO 73→72,9→10)도
  전부 별도 세션에서 코드로 재확인, 오차 있어도 1~3건 이내.

**두 차례에 걸친 이 진단 문서는 숫자 조작 없이 실제 코드 분석 결과로 판단됩니다.**

---

## 2. 핵심 발견 — Arm C1은 새로 만들 게 아니라 이미 있는 걸 확장해야 함

`data/v3/structured/table_atomic_facts_v3.2_1f29fca9...jsonl` (4,017행)가 제안된
sidecar와 **동일한 구조**입니다: `subject / attribute / value / unit / source_chunk_id /
start_offset / end_offset / heading_path / table_caption / status`.

`docs/v3/table_atomic_facts_arm1.md`에 따르면 이 arm은:

- **95문항 무회귀 확인 후 사용자 승인으로 v3 기본 runtime/canonical view에 이미 승격됨**
  (`docs/v3/v3_2_runtime_promotion.md`가 최신 상태를 관리).
- 적용 범위가 **의도적으로 좁게 제한**되어 있었음:
  - 소스 4개만: `dnf_game_guide`, `dnf_seria_shop`, `dnf_monthly_item`, `dnf_account_policy`
    (즉 `dnf_notice`, `dnf_update`, `dnf_event`, `dnf_faq`는 애초에 범위 밖)
  - 표 종류도 "가격/판매기간/삭제일/유효기간" caption이 있는 표로 한정

**왜 문제가 안 잡혔는지 설명됨**: 디레지에 문서는 범위 안(`dnf_game_guide`)인데도
atomic fact가 **0건**입니다 — "입장 명성/권장 명성/피로도" 표는 가격·기간 카테고리가
아니라서 Arm 1이 아예 건드리지 않았습니다. "최후의 과업"은 `dnf_update` 소스라 4개
소스 범위 밖입니다.

**결론**: C1은 "새 스키마 설계"가 아니라 **"이미 검증·승격된 Arm 1의 범위를 (a) 8개
소스 전체로, (b) 가격/기간 외 스탯·요구조건 표까지 확장"**하는 작업입니다. 스키마
리스크 없이 이미 통과한 코드 경로를 넓히기만 하면 됩니다.

---

## 3. 전체 평가

- A~G 원인 분해는 타당합니다. "검색만 고치면", "LLM만 강하게" 식 단일원인 사고를
  피한 것이 맞는 방향이며, 이번 세션에서 typed_evidence_ref 32문항 검수 중 직접
  겪은 문제(slot 8의 게시일/적용일 혼동, slot 21의 정책 개정본 혼동)와 정확히
  같은 근본 원인(문제 5: 시간 메타데이터 미구조화)입니다.
- **구조적 지적 한 가지**: B(같은 subject, 다른 scope)와 C(distractor에 묻힘)가
  실무에서는 겹칩니다. 디레지에 사례 자체가 "검색이 입장명성/권장명성을 구분
  못함(C) = relation이 구조화 안 됨(B)"이라 같은 원인입니다. 좋은 소식은 Arm 1
  확장 하나가 B/C를 동시에 해결한다는 것 — ROI가 큰 이유입니다.
- 7번 "하지 말아야 할 것" 목록은 이 프로젝트가 이미 지켜온 규율(불변 원본, 물리
  삭제 금지, 슬롯별 수작업 정답 금지, 검증 없는 승격 금지, 변수 동시 변경 금지)과
  정확히 일치. 새 원칙이 아니라 기존 규율의 재적용입니다.

---

## 4. 7개 질문에 대한 답

**Q1. corpus/retrieval/generator/verifier 책임분리가 타당한가?**
타당하나, D(질문 다의성)와 E(불완전 목록을 full로 선언)는 하나의 메커니즘으로 묶어야
합니다 — 둘 다 "검색된 후보의 개수·다양성"이라는 같은 신호로 판정 가능합니다(Q4 참고).

**Q2. section/table evidence sidecar 최소 스키마는?**
새로 설계하지 말고 `table_atomic_facts_v3.2`의 기존 필드를 그대로 재사용하세요.
여기에 typed_evidence_ref의 `value_type` 정규화(통화/불리언 — 이번 세션에 고친 그
로직)를 **공유**시키는 게 핵심입니다. 새 필드는 `scope`(=`heading_path` 재사용)
정도만 추가.

**Q3. 동일 subject, 다른 scope(예: 최후의 과업 시나리오 vs 콘텐츠 채널) 구분 방법?**
Arm 1이 이미 `heading_path` + 표의 "구분" 컬럼으로 부분 처리 중입니다. 확장 시
"구분" 열이 있는 매트릭스 표(디레지에처럼 채널×난이도)를 명시적으로 처리하는 규칙만
추가하면 됩니다.

**Q4. 수작업 intent 규칙 없이 clarification을 결정하는 가장 단순한 방법?**
리트리벌 결과의 모양(shape)만으로 판정: 같은 relation에 대해 서로 다른
(scope, value) 쌍이 top-K에 2개 이상 있으면 clarification, 1개면 답변, relation
자체가 없으면 abstain. 언어 패턴 목록이 전혀 필요 없습니다.

**Q5. server evidence-ref 속도 유지하며 목록 불완전성·의미 오선택 막는 최소 검증?**
"종류/전부/모든" 같은 총망라 표현을 답변에서 감지하면, 서버가 같은 relation·같은
parent-table을 공유하는 모든 sibling row가 인용됐는지 기계적으로 대조 — 하나라도
빠지면 자동으로 partial 강등. quote 매칭 없이 E-ref 메타데이터만으로 가능해 속도
손실이 없습니다.

**Q6. 중복 삭제 없이 candidate diversity를 높이는 안전한 방법?**
제안대로 top-K 조립 단계에서 lineage dedup하되, 정책처럼 여러 revision이 겹치면
`is_current_revision`/`status` 필드로 현재판을 대표로 우선 선택하세요 — 이미
temporal overlay에 그 필드가 있습니다.

**Q7. C1~C5 중 가장 명확히 효과를 진단할 수 있는 실험 순서는?**
C1(→Arm1 확장)과 C3(시간 메타데이터)는 둘 다 "기존 텍스트에서 구조 추출"이라 **같은
측정 단위로 묶어서 한 번에 검증**을 추천합니다. C2(dedup)는 후보 구성 자체를 바꾸는
별개 변수라 분리 유지가 맞고, C4(boilerplate)는 이미 단독 실패(NO-GO) 전례가 있으니
C1/C3 이후로 미루는 게 맞습니다. C5는 C1 sidecar가 있어야 작동하니 마지막이 맞습니다.

---

## 5. 권장 실행 순서 (수정본)

```
1. Arm 1(table_atomic_facts) 확장
   - 소스 범위: 4개 → 8개 전체
   - 표 종류 범위: 가격/기간 → 스탯/요구조건/상태 표 포함
   - 스키마는 기존 그대로, typed_evidence_ref의 value_type 정규화 공유
   (기존 C1 + C3의 "게시일/적용일 분리, updated_at 추출" 포함해 한 번에 측정)
2. C2: 후보 조립 단계 dedup (원본 삭제 없이, lineage 기준, 정책은 is_current_revision 우선)
3. C4: boilerplate 제거 — 검색 텍스트와 evidence view 양쪽 동시 적용 (단독 적용 NO-GO 전례 있음)
4. C5: clarification — Q4의 mechanical shape rule 적용 (Arm 1 확장이 선행돼야 작동)
```

---

## 6. 하지 말 것 (원문 그대로 동의)

- canonical corpus 직접 덮어쓰기
- 중복 공식 문서 물리 삭제
- 개별 실패 질문에 맞춘 수작업 규칙/정답 삽입 (예: "초월 종류 = A+B")
- retrieval·chunking·generator·verifier 동시 변경
- 기존 retrieval-clean 코퍼스 무검증 승격
- adaptive 점수를 일반화 성능으로 보고

---

## 7. 절차적 메모

이 코퍼스 엔지니어링 트랙은 현재 보류 중인 typed_evidence_ref 봉인 결정(untouched32
32문항 최종 승인·freeze)과 **완전히 별개 트랙**입니다. 서로 막지 않게 병행 가능합니다.
