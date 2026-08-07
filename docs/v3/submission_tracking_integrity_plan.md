# 지시서 — 제출 전 추적 무결성 복구

작성: 2026-08-06
선행: `PORTFOLIO.md` 존재 (완료)
후속: `docs/v3/readme_entrypoint_rewrite_plan.md` (이 라운드 다음)
Qwen 호출 예산: **0회**

---

## 0. 왜 하는가

`PORTFOLIO.md`는 완성됐지만 **저장소를 클론한 사람은 그 주장을 검증할 수 없다.**

실측한 현재 상태:

```
미추적   815 파일 / 114.0 MB
변경      29 파일
```

여기서 세 가지 문제가 확인됐다.

### 0-1. PORTFOLIO.md가 거는 링크 6개가 미추적이다

```
reports/v3/product_free_rag_a6_one_shot_4d47ef5d...jsonl   ← 공식 봉인 결과 원본
reports/v3/typed_evidence_ref_relation_inventory_96_20260727.json
reports/v3/product_table_introducer_s1_20260805.jsonl
docs/v3/product_free_rag_table_subject_binding_results_20260805.md
data/v3/runtime/free_minimal_runtime_snapshot_v1.json
```

첫 줄이 특히 심각하다. **헤드라인 `sealed 20/32`의 원본 증거 파일**이며,
GitHub에 올리면 링크가 깨져 아무도 확인할 수 없다.

### 0-2. 회귀 `1,269 passed`가 클론에서 재현되지 않는다

```
미추적 테스트 파일        42개
그 안의 test_ 함수      약 360개
미추적 src/v3 모듈        93개
추적 테스트 → 미추적 src 의존   0건   ← 클론이 깨지진 않음
```

클론은 정상 동작하지만 테스트 수가 크게 줄어 `1,269`가 나오지 않는다.
정직한 측정을 표방하는 문서가 **자기 검증 수치를 재현 불가능하게** 주장하는 상태다.

### 0-3. `tmp/` 37.7 MB가 커밋 대기 중이다

```
tmp/imagegen/*.gif        4.6 MB × 3
tmp/imagegen/*.png        1.4 MB × 다수
tmp/ 합계                 127 파일 · 37.7 MB
```

이미지 생성 작업물이다. 실수로 `git add .` 하면 영구히 history에 들어간다.

---

## 1. 이 라운드의 목표

> **클론한 사람이 `PORTFOLIO.md`의 주장을 직접 확인할 수 있게 만든다.**

숫자를 바꾸지 않는다. 파일을 지우지 않는다. **추적 상태만 고친다.**

---

## 2. 절대 하지 말 것

- `git add .` / `git add -A` — 114 MB가 통째로 들어간다
- `tmp/` 커밋
- 파일 삭제 (`rm`, `git rm`)
- 봉인 artifact 수정
- 평가·코퍼스·인덱스 재실행
- `PORTFOLIO.md` 본문 수정 (이 라운드는 추적만)
- `README.md` 수정 (다음 라운드)
- `app/` 추가 커밋

---

## 3. 단계

### T0 — `tmp/` 차단 (먼저 한다)

`.gitignore`에 추가한다.

```
tmp/
```

**T0을 가장 먼저 하는 이유**: 이후 단계에서 실수로 광범위 `add`를 해도
37.7 MB가 들어가지 않게 하는 안전장치다.

게이트: `git status --porcelain | grep "^?? tmp/"` 출력 **0줄**

### T1 — 링크 대상 커밋

`PORTFOLIO.md`, `PORTFOLIO_REPORT.md`, `PORTFOLIO_V3_DRAFT.md` 세 문서가
거는 **모든 로컬 링크**를 추출해 미추적인 것을 커밋한다.

파일을 하나씩 명시적으로 `git add` 한다. 디렉터리 통째로 하지 않는다.

확인된 6개 외에 더 있을 수 있으므로 **직접 재추출**할 것.

게이트:

- [ ] 세 문서의 로컬 링크가 **전부** `git ls-files` 에 있다
- [ ] 커밋에 `tmp/` 파일 0건

### T2 — 회귀 재현성 복구

목표: 클론에서 `1,269 passed / 2 failed` 가 나오게 한다.

1. `tests/v3` 미추적 42개를 커밋한다
2. 그 테스트들이 import 하는 `src/v3` 모듈 중 미추적인 것을 커밋한다
   (**의존 그래프를 따라간다.** 미추적 93개를 전부 넣지 않는다)
3. 테스트가 여는 **fixture·artifact 경로** 중 미추적인 것을 커밋한다

**검증 — 실제 클론에서 확인한다**

```bash
git clone --no-hardlinks . <스크래치 경로>
cd <스크래치 경로>
python -m pytest tests/v3 -q
```

기준: **1,269 passed / 2 failed.** 실패 2건은 기존 SHA 면제 항목과
같은 이름·같은 사유여야 한다.

숫자가 다르면 부족한 파일을 특정해 추가하고 다시 클론 검증한다.
**클론 검증 없이 통과로 보고하지 말 것.**

게이트:

- [ ] 클론에서 1,269 passed / 2 failed
- [ ] 실패 2건의 이름과 사유가 기존과 동일
- [ ] 커밋한 `src/v3` 모듈이 의존 그래프로 정당화된다 (목록과 근거 보고)

### T3 — 나머지 미추적 처분 (조사만, 실행 금지)

T1·T2 이후에도 남는 미추적을 분류해 **표로 보고만** 한다.

| 경로 | 남은 개수 | 용량 | 제안 | 근거 |
|---|---:|---:|---|---|
| `reports/v3` | | | | |
| `outputs/v3` | | | | |
| `data/v3` | | | | |
| `src/v3` | | | | |
| `docs/v3` | | | | |
| 기타 | | | | |

제안은 `커밋` / `.gitignore` / `보류` 중 하나로 하고 이유를 적는다.
**실행하지 않는다.** 사용자 결정 사항이다.

특히 다음은 판단 근거를 반드시 적을 것.

- `data/v3/structured/table_atomic_facts_v3.2_a1b69f...jsonl` (18.6 MB)
- `outputs/v3` 93 파일 / 23.8 MB

### T4 — 최종 확인

- [ ] 봉인 SHA 2개 불변
      `9405401d...65dc` / `4d47ef5d...8499`
- [ ] `PORTFOLIO.md` 무변경 (`git diff` 빈 출력)
- [ ] `README.md` 무변경
- [ ] `app/` 추가 커밋 0건
- [ ] `tmp/` 커밋 0건

---

## 4. 커밋 분리

되돌리기가 쉽도록 나눈다.

```
1) chore: ignore tmp/
2) docs: track portfolio-linked artifacts
3) test: track v3 regression suite files
```

T3은 조사만이므로 커밋 없음.

---

## 5. 보고 양식

```markdown
## T0 tmp 차단
- .gitignore 추가: 완료
- 잔여 `?? tmp/`: 0줄

## T1 링크 대상
- 재추출한 로컬 링크 총수:
- 미추적이었던 파일 목록:
- 커밋:

## T2 회귀 재현성
- 커밋한 tests/v3 파일 수:
- 커밋한 src/v3 모듈 수 / 의존 근거:
- 커밋한 fixture·artifact 수:
- **클론 검증 결과**:  passed /  failed
- 실패 2건 이름·사유 일치:
- 클론 경로:
- 커밋:

## T3 나머지 처분 (조사)
| 경로 | 개수 | MB | 제안 | 근거 |

## T4 최종
- 5개 항목 각각 통과 / 실패

## 남은 것
```

---

## 6. 성공 기준

이 라운드가 끝나면 다음이 성립해야 한다.

```
저장소를 클론한 사람이
  · PORTFOLIO.md의 모든 링크를 열 수 있다
  · pytest 를 돌려 문서에 적힌 1,269 를 직접 확인할 수 있다
```

**검증할 수 없는 주장은 정직한 측정이 아니다.** 이 라운드는 숫자를 만드는
게 아니라, 이미 만든 숫자를 남이 확인할 수 있게 여는 작업이다.

---

## 7. 다음

이 라운드 통과 후 `docs/v3/readme_entrypoint_rewrite_plan.md` 를 진행한다.
그 지시서의 선행 조건(`PORTFOLIO.md` 존재)은 이미 충족돼 있다.
