# README 진입점 재작성 결과

작성: 2026-08-06  
구조 설명 갱신: 2026-08-07  
기준 지시서: `docs/v3/readme_entrypoint_rewrite_plan.md`

## 미커밋 변경 처리

- 되돌린 diff 요약: 낡은 v3 요약 수치 갱신 24 insertions / 12 deletions를 제거하고 커밋 기준 README로 복원했다.
- 보존 위치: `reports/v3/readme_pre_rewrite_uncommitted_diff_20260806.patch`
- 보존 파일 SHA-256: `58ef6e832518e730dc2d2f156fb31b3aea3c0b19f4e94f6fa0be48dc6dfe895d`
- 버린 근거: 미커밋 변경의 회귀 수치 `875 passed`도 2026-08-06 실측 `1,269 passed / 2 failed`보다 낡았고, 이 라운드는 과거 v3 상태 블록을 유지하는 대신 현재 포트폴리오로 진입시키는 것이 목적이다.

## 새 README

- 총 줄 수: 원본 복원 후 495줄 → 재작성 후 488줄
- 최상단 포트폴리오 링크: 5번째 줄
- 교체한 블록: 영문 프로젝트 소개, `Latest v3 research track`, `Latest Verified Status`
- 격하한 절: Current Scope, Data, Setup, Build Indexes, Regenerate Official Eval and Train QA, Regenerate RAFT Data, Evaluate Retrieval, Evaluate Answers, Label Classifier Baseline, Label Studio, LoRA/QLoRA Scaffold, Run Demo, Smoke Tests, Final Limitations
- 격하 방식: `## v1/v2 재현 (레거시)`를 Current Scope 앞으로 옮기고 위 절을 모두 3단계 제목으로 낮췄다. 일반 고지인 Data Source Notice는 레거시 절 밖의 2단계 제목으로 유지했다.
- 기존 command block: 23개 유지
- command block 전후 SHA-256: `039ecb8c22b9f6fdcb5d28044b1a947868fef140bdb51d8478fcd99353770821` 일치

미추적 수는 파일 기준 588개다. `git status --porcelain`의 `??` 항목은 미추적 디렉터리를 한 줄로 접어 578개로 보이고, `--untracked-files=all`의 `??` 항목은 파일을 펼쳐 588개로 보인다. 차이는 회귀 실행 산출물이 아니라 표시·집계 단위에서 생긴다.

## 수치 대조

| 항목 | README | `PORTFOLIO.md` §0 | 일치 |
|---|---:|---:|---|
| v3 typed, sealed | 37/64 | 37/64 | 통과 |
| Product Free RAG A6, sealed 자동 채점 | 7/32 (21.9%) | 7/32 (21.9%) | 통과 |
| Product Free RAG A6, sealed 사람 감수 | 20/32 (62.5%) | 20/32 (62.5%) | 통과 |
| 제품 기본 경로 승격 | NO-GO | NO-GO | 통과 |

코퍼스 스냅샷도 `PORTFOLIO.md` §8-2와 동일하게 기록했다.

```text
2026-07-17 수집 · 07-18 정규화 · 07-21 검색용 청크 확정
문서 980 · 청크 3,599
discover_sources → collect_details → 정규화 → 청킹
→ BM25 재빌드 → dense 재임베딩
```

## 게이트

- [x] 미커밋 변경을 되돌렸고 버린 diff를 별도 patch에 보존했다.
- [x] 최상단 5줄 안에 `PORTFOLIO.md` 링크가 있다.
- [x] 결과 수치가 `PORTFOLIO.md` §0과 일치한다.
- [x] 결과 수치에 sealed 라벨이 있다.
- [x] 자동 채점과 사람 감수를 구분했다.
- [x] `37/64`와 `20/32`를 우열 비교하는 문장이 없다.
- [x] 날짜가 명시된 코퍼스 스냅샷 3줄이 있다.
- [x] v1/v2 command block 23개의 내용과 SHA가 동일하다.
- [x] `PORTFOLIO.md`, `app/`, 코퍼스 관련 추적 파일을 변경하지 않았다.
- [x] 회귀가 `1,269 passed / 2 failed`로 유지됐다. 두 실패는 기존 SHA 면제 항목과 동일하다.

## 회귀 상세

```text
2 failed, 1269 passed, 2 warnings, 67 subtests passed

test_retrieve_decomposed.py::DecomposedHybridArtifactTest::
  test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings

test_run_unified_runtime.py::UnifiedRuntimeArtifactTest::
  test_full_replay_is_content_addressed_and_reproducible
```

Qwen 호출, 평가 실행, 코퍼스 재생성, 인덱스 재빌드는 하지 않았다.

## 남은 것

- 제출 커밋은 README, 이번 결과 문서, 보존 patch 세 파일만 대상으로 한다.
- 기존 작업 트리의 다른 사용자 변경과 미추적 실험 산출물은 건드리지 않았다.
