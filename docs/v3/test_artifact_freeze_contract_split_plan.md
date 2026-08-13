# 지시서 — 회귀 테스트의 frozen-artifact 재생성 계약 분리

작성: 2026-08-13
Qwen 호출: 전 구간 **0회** (생성 모델과 무관한 순수 코드/테스트 작업)

---

## 0. 문제

제출 전 감사에서 발견됐고 내가 직접 재현했다. 새 clone에서
`python -m pytest tests/v3 -q`를 돌리면:

```
2 failed, 1370 passed, 67 subtests passed
```

**종료 코드가 0이 아니다.** 더 큰 문제는 실행 후 `git status`가 더 이상
깨끗하지 않다는 것이다 — 새 clone에서 전체 스위트를 한 번 돌리면
**추적 디렉터리 안에 14개의 새 파일이 생긴다.**

```
data/v3/decomposition/decomposed_hybrid_manifest_d1cd565b98...json
data/v3/decomposition/question_decomposition_manifest_ab777ec9f7...json
data/v3/evidence/bounded_candidate_source_fallback_manifest_ddc17362...json
data/v3/evidence/question_partial_context_ab_manifest_67b88fd46d...json
data/v3/evidence/question_partial_hybrid_ab_manifest_aa00c18dc1...json
data/v3/normalized/normalized_corpus_manifest_bca731b533...json
data/v3/router/question_router_manifest_18f6ec70eb...json
data/v3/runtime/unified_runtime_manifest_9a7916f92...json
reports/v3/decomposed_hybrid_e1855d8caa...json
reports/v3/document_v3_promotion_a5bd2d8111...json / .md
reports/v3/question_decomposition_cfa3112f68...json
reports/v3/question_router_8a22b2b2c9...json
reports/v3/unified_runtime_2a0eb5fcef...json
```

**직접 재현해서 확인한 것**: 이 목록은 실패한 테스트 2개만의 결과가
아니다. `freeze_*` 계열 함수(`freeze_decomposed_hybrid`,
`freeze_unified_runtime` 등)는 결과를 **호출 즉시 실제 추적 디렉터리에
content-addressed 파일명으로 저장**한다. 이 파일명은 이번 실행의
데이터를 해시한 값이라, 코퍼스가 예전에 얼려둔 시점(frozen SHA)과
달라지면 **어서션이 실패하기도 전에 이미 새 파일이 디스크에 써진다.**

```
tests/v3/test_retrieve_decomposed.py:296-329
  DecomposedHybridArtifactTest::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings
  → freeze_decomposed_hybrid(**kwargs)를 두 번 호출(자기 자신과 비교) +
    반환된 SHA를 FROZEN_CASES/FROZEN_MANIFEST/FROZEN_REPORT/FROZEN_REPORT_MD
    파일의 SHA와 비교
  → 실패 지점: tests/v3/test_retrieve_decomposed.py:323

tests/v3/test_run_unified_runtime.py:141-149
  UnifiedRuntimeArtifactTest::test_full_replay_is_content_addressed_and_reproducible
  → freeze_unified_runtime(root=self.ROOT) 호출 (실제 저장소 루트)
  → 반환된 SHA를 클래스 상수 CASES_SHA/MANIFEST_SHA와 비교
  → 실패 지점: tests/v3/test_run_unified_runtime.py:149
```

**왜 실패하는가**: 코퍼스가 8월에 여러 번 갱신되면서, 이 두 테스트가
기대하는 예전 SHA와 오늘 재생성한 결과의 SHA가 달라졌다. **이건 버그가
아니라 corpus drift다.** 문제는 "달라서 실패한다"가 아니라 "달라서
실패하는 동시에 디스크에 파일까지 남긴다"는 것이다.

---

## 1. P0 — 실태 조사 (변경 0)

**하지 말 것: 바로 두 테스트부터 고치지 말 것.** 먼저 범위를 정확히 잰다.

### 조사 항목

1. `tests/v3/` 전체에서 `freeze_*` 계열 함수를 실제 저장소 경로(root
   기반, `tmp_path`가 아닌)로 호출하는 테스트를 전부 찾는다. 지금 실패
   중인 2개 외에, **지금은 통과하지만 같은 방식으로 파일을 쓰는 테스트**가
   몇 개인지 정확히 센다. (위 14개 파일 목록 중 최소 6개는 지금 통과하는
   다른 테스트에서 나온 것으로 보인다 — `document_v3_promotion`,
   `question_router` 등. 직접 확인할 것.)
2. 각 `freeze_*` 함수가 실제로 파일을 쓰는 지점(코드 줄)을 찾는다.
3. 이 파일 쓰기가 **프로덕션에서 의도된 동작**(실제 승격 라운드에서
   artifact를 얼릴 때 씀)인지, **테스트에서 재사용하다 보니 생긴 부작용**
   인지 함수별로 구분한다.

### P0 게이트

- [ ] 코드 변경 0
- [ ] "지금 통과하지만 같은 문제가 있는 테스트" 개수를 정확히 보고했다
- [ ] freeze 함수의 파일 쓰기가 프로덕션 용도인지 테스트 재사용 부작용인지
      함수별로 판정했다

산출물: `reports/v3/test_artifact_freeze_contract_split_survey_20260813.json`

---

## 2. P1 — 설계안 (구현 전 보고)

P0에서 찾은 범위 전체에 아래 계약 분리를 적용할지, 우선 실패 중인 2개만
먼저 고치고 나머지는 별도 라운드로 미룰지 결정한다. **최소 실패 중인
2개는 반드시 포함.**

### 분리 원칙

**하나의 어서션이 두 가지를 동시에 확인하지 않는다.**

```
과거 어서션 (지금)
  freeze_X()를 호출 → 반환 SHA를 frozen 파일의 SHA와 비교
  → "생성기가 결정적인가"와 "코퍼스가 그때와 같은가"가 뒤섞여 있고
    후자가 깨지면 전자도 같이 실패한 것처럼 보인다

분리 후
  (a) 과거 봉인 artifact 무결성      frozen 파일을 읽기만 해서
                                    file_sha256(FROZEN_X) == 기록된 SHA
                                    상수인지 확인. freeze_X()를 호출하지
                                    않는다. 코퍼스 drift와 무관하게
                                    항상 안정적이어야 한다.

  (b) 생성기 재현성                  freeze_X()를 tmp_path 아래 출력
                                    경로로 두 번 호출해 두 결과가
                                    서로 일치하는지만 본다. frozen 상수와
                                    비교하지 않는다.
```

`freeze_*` 함수가 출력 경로를 인자로 안 받고 항상 저장소 루트 기준
경로에 쓰도록 하드코딩돼 있다면, (b)를 위해 출력 경로를 주입 가능하게
바꿔야 할 수 있다 — **이 경우 함수 시그니처 변경 범위를 P1에 반드시
보고할 것.** 프로덕션 호출부(승격 스크립트 등)가 있다면 그쪽 인자도
같이 확인한다.

### P1 게이트

- [ ] 실패 중인 2개 테스트의 분리 설계를 구체적으로 제시했다
- [ ] P0에서 찾은 나머지(통과 중이지만 같은 패턴인) 테스트를 이번에 같이
      할지, 별도 라운드로 미룰지 명시하고 이유를 댔다
- [ ] freeze 함수 시그니처를 바꿔야 하면 그 영향 범위(다른 호출부)를
      보고했다
- [ ] 구현을 시작하지 않았다

---

## 3. P2 — 구현 (승인 후)

```
· frozen 상수(FROZEN_CASES 등, CASES_SHA/MANIFEST_SHA 등)는 절대 오늘
  값으로 바꾸지 말 것 — 그건 "재봉인"이지 "계약 분리"가 아니다
· (a) 읽기 전용 검증은 freeze_*를 호출하지 않는다
· (b) 재현성 검증은 pytest의 tmp_path fixture로 출력 위치를 격리한다
· 변경은 P1에서 승인된 범위 안에서만
· 회귀 테스트 추가 없이 기존 두 테스트를 재구성하는 작업이므로 새 테스트
  파일 난립 금지 — 같은 클래스 안에서 메서드를 나눈다
```

---

## 4. P3 — 검증

```
1. 새 clone에서 pip install → pytest tests/v3 -q
2. 종료 코드 확인:            echo $?  (0이어야 한다)
3. 실행 전후 git status 비교:  완전히 동일해야 한다 (파일 0개 생성)
4. 실패했던 두 테스트가 이제 무엇을 검증하는지 각각 한 줄로 보고
5. sealed 관련 다른 테스트 회귀 없음 확인 (전체 스위트 재실행)
```

### P3 게이트

- [ ] 새 clone 기준 `pytest tests/v3 -q` 종료 코드 0
- [ ] 실행 전후 `git status` 완전히 동일
- [ ] 기존 1,370개 통과 테스트 전부 유지
- [ ] frozen SHA 상수를 하나도 안 바꿨다

---

## 5. 하지 말 것

- frozen SHA 상수를 오늘 재생성된 값으로 갱신 (재봉인은 이 라운드의
  목적이 아니다)
- 두 테스트를 `skip`/`xfail`로 덮기
- P1 승인 전 구현 착수
- sealed A6 관련 artifact·테스트 건드리기
- `app/ui/` 수정
- `git add .`

---

## 6. 보고 양식

```markdown
## P0 조사
- freeze_* 를 실제 경로로 호출하는 테스트 전체 목록:
- 그중 지금 통과 중인데 같은 패턴인 것: 개
- 함수별 파일 쓰기가 프로덕션용/테스트 부작용인지:

## P1 설계
- 실패 중인 2개 분리 설계:
- 나머지 포함 여부와 이유:
- 함수 시그니처 변경 필요 여부:

## P2 구현 (승인 후)
- 변경 파일/함수:

## P3 검증
- 새 clone pytest 종료 코드:
- 실행 전후 git status diff:
- 전체 통과 수:
- 판정: 채택 / 롤백
```
