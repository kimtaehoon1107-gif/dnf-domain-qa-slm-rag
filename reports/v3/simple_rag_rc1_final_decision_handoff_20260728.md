# 사이드 채팅 인계 — DNF Simple RAG RC1 최종 결정

작성일: 2026-07-28

## 1. 최종 결정

현재 프로젝트는 규칙을 더 추가하지 않고 다음 구성을 포트폴리오·연구 데모용
RC1으로 동결하는 것이 가장 타당하다.

```text
Product Router
→ BM25 + BGE-M3 hybrid top 20
→ BGE-reranker-v2-m3 top 5
→ 전역 후보 fallback 1개, 최종 최대 6개
→ qwen3-8b:ctx8192
→ 원문 청크 기반 답변 + chunk ID 인용
→ A1~A3 최소 검증
   - 월·연도·revision 불일치 차단
   - 게시일·적용일 등 temporal-role 불일치 차단
   - 명백한 relation-value 불일치 차단
   - 인용 후보 실재 및 숫자·날짜·단위 확인
→ 실패 시 partial/abstain
```

권장 이름:

```text
DNF Simple RAG RC1 — Product Router + Minimal Safety Guards
```

판정:

```text
포트폴리오·연구 데모: GO
실제 제품 기본 승격: NO-GO
```

## 2. 이 구성을 선택한 근거

사람 검수 후 봉인된 untouched 32문항 최초 실행 결과:

| Arm | 의미상 완전 정답 | 실제 false-full | 생성 오류 |
|---|---:|---:|---:|
| A0 완전 기본 RAG | 15/32 (46.9%) | 0 | 1 |
| A1~A3 baseline | 15/32 (46.9%) | 0 | 1 |
| Frozen B1+B3+B4 | 16/32 (50.0%) | 1 | 1 |

저장된 동일 Qwen 원출력을 verifier-only replay한 결과 A0와 A1~A3의 사용자
노출은 `32/32` 모두 동일했다. 따라서 A1~A3는 untouched 정답률을 높인 기능이
아니라, 명시적인 월·연도·relation·temporal 충돌을 낮은 비용으로 차단하기 위한
방어 계층으로 유지한다.

Frozen B1+B3+B4는 24번을 복구했지만 27번에서 `DNF 폴리스` 대신
`나비 무도회·아라드 패스 웨딩` 상품 구성품을 합쳐 full answer로 노출했다.
정답 한 건 증가보다 실제 false-full 0이 더 중요하므로 A1~A3를 선택한다.

동일 최초 실행에서 추가로 확인된 내용:

- 사람 기준 정답 후보 보유: 25/32
- 인용 좌표 복원: 32/32
- 실제 false-full은 0이지만, 27번에 근거가 부정확한 partial 1건이 존재
- 평균 생성 시간: 30.97초
- p95 생성 시간: 46.62초
- adaptive 세트에서 기록했던 `22/32, false-full 0`은 재현되지 않음

이 최초 end-to-end 실행은 `f34eec0`의 `dnf-simple-domain-rag-v2`를 사용했다.
이후 requirements-aware Router v3로 수행한 retrieval-only adaptive 진단과
동일한 실행 코드가 아니며, Router v3 검색 수치를 RC1 end-to-end 점수로
해석하지 않는다.

관련 보고서:

- `reports/v3/simple_rag_original_vs_b134_untouched32_one_shot_human_review_20260728.md`
- `reports/v3/simple_rag_original_vs_b134_untouched32_one_shot_20260728.json`
- `outputs/v3/untouched/simple_rag_original_vs_b134_untouched32_one_shot_20260728.jsonl`

## 3. 검색 계층 판단

두 개의 이미 실행된 32문항 세트에서 Vanilla와 현재 Product Router를
retrieval-only로 비교한 adaptive 진단:

| 검색 구성 | strict 후보 회수 | 사람 기준 직접 근거 회수 |
|---|---:|---:|
| Vanilla hybrid + reranker | 43/64 | 44/64 |
| Product Router + 동일 검색/reranker | 51/64 | 55/64 |

Product Router가 검색 계층에서는 Vanilla보다 낫다. 따라서 최종 RC1의 검색으로
유지한다.

단, `51/64`와 `55/64`는 두 세트 결과를 이미 본 뒤 수행한 adaptive retrieval
diagnostic이다. 일반화 점수나 최종 제품 점수로 사용하면 안 된다.
이 진단은 requirements-aware Router v3 코드로 수행했으며, 최초 untouched
end-to-end의 Router v2와 분리해 기록한다. RC1의 재현 가능한 성능 기준은
Router v2 `f34eec0`이고, Router v3는 비승격 검색 연구 결과다.

관련 보고서:

- `reports/v3/retrieval_vanilla_vs_product_router_two32_20260728.json`
- `reports/v3/retrieval_vanilla_vs_product_router_two32_human_review_20260728.md`
- `reports/v3/retrieval_two_32sets_crosscheck_20260728.md`

## 4. 현재 핵심 병목

검색은 개선됐지만 end-to-end 정답률은 안정적으로 개선되지 않았다.

```text
정답 근거를 검색함
→ Qwen3 8B가 잘못된 값을 선택하거나 일부 요구를 포기
→ verifier가 정상 답변을 막거나 형제 상품의 잘못된 근거를 통과
```

untouched 32에서 사람 기준 후보는 25문항에 있었지만 완전 정답은 15문항이었다.
따라서 현재 주된 병목은 검색보다 생성기의 의미 선택과 verifier의
subject/relation/identity 판단이다.

규칙을 추가하면 특정 문항은 복구되지만 다른 문항에서 회귀 또는 false-full이
발생했다. Qwen3 8B에 adaptive 규칙을 계속 추가하는 것은 중단한다.

## 5. 기본 경로에서 제외할 실험

다음 기능은 실험 기록으로 보존하되 RC1 기본 경로에는 승격하지 않는다.

- Frozen B1+B3+B4 인용 복구
- Typed evidence-ref / Claim Contract v8
- relation-semantic selector
- subject-anchored 추가 검색
- semantic fallback
- 형제 청크를 이용한 자동 인용 복구

권장 feature 상태:

```text
b134_citation_repair_enabled = false
typed_evidence_ref_enabled = false
relation_semantic_selector_enabled = false
subject_anchored_search_enabled = false
semantic_fallback_enabled = false
```

## 6. 포트폴리오에서 보고할 숫자

숫자의 위상을 섞지 않는다.

### 최초 untouched end-to-end

```text
의미상 완전 정답: 15/32 = 46.9%
실제 false-full: 0/32
근거가 부정확한 partial: 1/32
생성 오류: 1/32
사람 기준 정답 후보 보유: 25/32
인용 좌표 복원: 32/32
```

### 검색 개선 adaptive 진단

```text
Vanilla 사람 기준 후보 회수: 44/64
Product Router 사람 기준 후보 회수: 55/64
차이: +11문항
```

`55/64`를 일반화 점수라고 부르지 않는다.

## 7. 프로젝트 마무리 순서

1. RC1의 모델 태그, `num_ctx`, prompt, 검색 top-k, reranker, fallback,
   verifier 설정, 코퍼스·인덱스 SHA를 기록한다.
2. RC1 관련 코드와 설정만 검토해 동결 커밋한다. 기존 dirty worktree의 다른
   사용자 변경은 건드리지 않는다.
3. 전체 회귀 테스트와 `git diff --check`를 실행한다.
4. 데모에 다음을 표시한다.
   - full / partial / unsupported
   - 답변
   - 원문 인용
   - 문서 제목·출처·날짜
   - 안전 검증으로 차단된 이유
   - RC1 전용 실행 경로: `python app/simple_rag_rc1_demo.py`
5. README 또는 포트폴리오 보고서에는 다음 흐름을 사용한다.

```text
Vanilla RAG
→ 검색 실패와 false-full 발견
→ Product Router로 후보 회수 개선
→ Typed/Claim Contract 실험
→ adaptive 상승이 untouched에서 재현되지 않음
→ 미니멀 안전 파이프라인으로 복귀
→ false-full 0인 RC1 선택
```

## 8. 추가 연구를 할 경우

Qwen3 8B에 규칙을 더 붙이지 않는다. 다음 실험은 별도 연구 브랜치에서 동일한
검색 후보와 동일한 최소 verifier를 고정한 모델 A/B만 수행한다.

```text
동일 Product Router
+ 동일 후보
+ 동일 최소 verifier
→ Qwen3 8B vs 더 강한 LLM
```

강한 LLM이 기존 개발 세트에서 정답률을 명확히 높이고 새 false-full을 만들지
않을 때만 새로운 untouched 평가로 이동한다.

## 9. 남아 있는 미개봉 평가 세트 주의

`data/eval/blind_test_v1.jsonl` 100문항은 사람 검수·봉인 후 아직 미개봉이다.

- SHA-256:
  `5ba916f8c9c1e78ceaaa160d3b6cf5557a697c12d847f50c63a89e7bb0e0793e`
- manifest: `reports/blind_test_v1_frozen_manifest.json`
- 평가 정책상 단 한 번의 의도적인 최종 실행만 허용

현재 불안정한 실험 선택을 위해 이 세트를 열지 않는다. RC1을 포트폴리오
후보로 마무리하는 데도 이 세트를 사용할 필요는 없다.

## 10. 본 채팅에서의 권장 다음 작업

새 성능 규칙을 구현하거나 같은 32문항을 다시 실행하지 않는다.

다음 중 하나만 선택한다.

1. 포트폴리오 마무리:
   RC1 설정 동결 → 테스트 → 선택 파일만 커밋 → README/데모 정리
2. 별도 제품 연구:
   RC1과 동일한 검색·검증 조건에서 더 강한 LLM과 통제 A/B

현재 권장은 1번이다.
