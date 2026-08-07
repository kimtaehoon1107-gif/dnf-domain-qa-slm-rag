# 지시서 — 저장소 정리·축소 (포트폴리오 공개 전)

작성: 2026-08-06
성격: 구조 정리. 파이프라인 동작·평가 숫자를 바꾸지 않는다.
선행 조건 없음. Qwen 호출 예산: **1회** (C3 스모크에서만)

---

## 0. 왜 하는가

포트폴리오 공개 시 저장소를 여는 사람은 다음을 본다.

```
클론 용량        약 530 MB  (.git pack 163 MB + 작업트리 366 MB)
추적 파일        2,019개
미추적 파일        677개
src/v3 스크립트    276개  (그중 59개는 아무데서도 참조 안 됨)
reports/v3        877개
최상위 포트폴리오 문서  2개  (PORTFOLIO_REPORT.md, PORTFOLIO_V3_DRAFT.md)
```

내용의 질과 무관하게 **"뭘 봐야 하는지 모르겠다"**가 첫인상이 된다.
이 라운드는 내용을 고치는 게 아니라 **찾을 수 있게** 만드는 것이다.

동시에 이 저장소는 **봉인 무결성이 프로젝트 정체성**이다. 정리하다
봉인 artifact를 건드리면 프로젝트의 핵심 주장이 무너진다. 그래서 이
지시서는 "지우자"가 아니라 **"지워도 되는 것을 증명하고, 되돌릴 수
있게 옮긴다"**로 설계했다.

---

## 1. 사전 조사 결과 (이미 실측함)

Codex가 다시 조사할 필요 없다. 아래는 확정된 관측이다.

### 1-1. 추적 용량 분포

| 경로 | 파일 | 용량 |
|---|---:|---:|
| `data/v3` | 510 | 244.2 MB |
| `data/processed` | 61 | 67.5 MB |
| `outputs/v3` | 139 | 24.4 MB |
| `reports/v3` | 564 | 11.1 MB |
| `src/v3` | 185 | 4.0 MB |
| `tests/v3` | 158 | 1.0 MB |
| `docs/v3` | 103 | 0.4 MB |

### 1-2. 핵심 패턴 — content-addressed 파일의 옛 세대가 전부 남아 있다

같은 논리 산출물이 SHA만 다른 채 3~4세대씩 공존한다.

```
data/v3/indexes/table_atomic_facts_arm1_embeddings_*.f32
    41.4 + 16.5 + 16.5 + 15.0 MB  = 89.4 MB   (4세대)

data/v3/structured/table_atomic_facts_v3.2_*.jsonl
    18.6 + 7.5 + 7.2 + 6.6 + 6.3 MB = 46.2 MB (5세대)

data/v3/structured/policy_clause_children_v3.2_*.jsonl
    10.8 + 10.8 MB = 21.6 MB                  (2세대)

data/v3/indexes/dense_full_embeddings_*.f32
    14.7 + 14.7 MB = 29.4 MB                  (2세대)
```

런타임이 실제로 여는 건 각 계열에서 **1세대뿐**일 가능성이 높다.
단, 이건 **가설이며 C0에서 증명해야 한다.**

### 1-3. 끝난 실험의 중간 점수 파일

`data/v3/evidence/` 상위 6개만 101 MB.

```
federated_retrieval_ab_segment_scores_*        21.9 MB
corpus_hygiene_federated_segment_scores_*      21.5 MB
requirement_retrieval_ab_segment_scores_*      16.0 MB
requirement_retrieval_ab_segment_scores_*      15.8 MB
faq_title_dedup_view_v3.2_*                    14.7 MB
extractive_assembler_v3_merged_scores_*        11.4 MB
```

전부 종료된 A/B 라운드의 세그먼트 점수다. 결론은 이미 `reports/v3`의
md에 기록돼 있다.

### 1-4. legacy 학습 데이터

`data/processed` 67.5 MB, `domain_raft_*.jsonl` 12개 이상.
v1/v2 SLM 파인튜닝 시절 산출물이며 현재 RAG 파이프라인은 쓰지 않는다.
**단, 포트폴리오 1막이 이 시절을 다루므로 "안 쓰니까 삭제"는 성급하다.**

### 1-5. 참조되지 않는 스크립트

`src/v3/*.py` 276개 중 **59개**가 테스트·다른 모듈·app 어디에서도
이름이 등장하지 않는다.

> 주의: 이 수치는 파일명 문자열을 정규식으로 훑은 것이다.
> 동적 import·`subprocess`·문서 내 명령줄 참조는 잡지 못한다.
> C0에서 그 세 경로를 반드시 추가 확인할 것.

### 1-6. 클론 용량은 작업 트리 정리로 줄지 않는다

```
.git pack    163 MB   ← 파일을 지워도 그대로
작업 트리    366 MB   ← 이 라운드가 줄일 수 있는 부분
```

**이 문제는 C4에서 옵션만 제시하고 실행하지 않는다.** 사용자 결정 사항이다.

---

## 2. 절대 건드리지 말 것 (불가침 목록)

아래는 **이동·삭제·gitignore 모두 금지**다. 하나라도 어기면 라운드 전체 롤백.

### 2-1. 봉인 artifact

```
data/v3/evaluation/product_free_rag_a6_frozen_9405401d...jsonl
data/v3/evaluation/product_free_rag_a6_freeze_manifest_4d47ef5d...json
data/v3/evaluation/product_free_rag_a6_one_shot_4d47ef5d..._journal.jsonl
reports/v3/product_free_rag_a6_one_shot_4d47ef5d...jsonl
reports/v3/product_free_rag_a6_slot6_readjudication_20260806.json
docs/v3/product_free_rag_a6_final_adjudication.md
```

`typed_evidence_ref` 계열 봉인·adjudication artifact도 동일하게 취급한다.
파일명에 `frozen` / `freeze_manifest` / `one_shot` / `sealed` /
`adjudication` / `readjudication` 이 들어가면 **먼저 불가침으로 가정**하고,
아니라는 증명이 있을 때만 후보에 넣는다.

### 2-2. 테스트가 SHA로 검증하는 파일

기존 면제 2건이 SHA를 비교한다.

```
tests/v3/test_retrieve_decomposed.py::test_actual_adaptive_pilot_refreezes_from_frozen_child_embeddings
tests/v3/test_run_unified_runtime.py::test_full_replay_is_content_addressed_and_reproducible
```

이 두 테스트가 **현재도 실패 중**이라는 사실이 "그러니 관련 파일은
지워도 된다"는 뜻이 아니다. 실패 사유가 SHA 불일치이므로, 파일을
지우면 실패 사유가 바뀌어 원인 추적이 불가능해진다.

### 2-3. 런타임 필수

```
data/v3/chunks/
data/v3/indexes/  중 현재 런타임이 여는 세대
data/v3/structured/ 중 현재 런타임이 여는 세대
```

"현재 세대"가 무엇인지는 **C0의 산출물**이다. 그 전에는 전부 불가침.

---

## 3. 단계 — 실패하면 즉시 중단하고 보고

### C0 — 참조 그래프 (삭제 금지 화이트리스트 확정)

**Qwen 0회. 이 단계는 아무것도 옮기거나 지우지 않는다.**

`data/`, `outputs/`, `reports/` 아래 모든 파일에 대해, 다음 4개 경로로
참조 여부를 전수 조사한다.

1. **정적 문자열 참조** — `src/`, `tests/`, `app/` 전체에서 파일명 또는
   그 SHA(64자 hex)가 등장하는가
2. **manifest 참조** — `*manifest*.json`, `*frozen*.jsonl` 내부가 그
   파일 경로/SHA를 가리키는가 (매니페스트끼리 연쇄 참조하므로
   **전이 폐포까지** 따라갈 것)
3. **subprocess / 동적 경로** — `Path(` · `glob(` · `os.path.join(`
   으로 조립되는 경로 패턴에 걸리는가
4. **문서 명령줄** — `docs/` md 안의 실행 명령에 등장하는가

산출물:

```
reports/v3/repo_consolidation_reference_graph_20260806.json
  {
    "file": "...",
    "size_bytes": N,
    "tracked": true|false,
    "referenced_by": ["src/v3/x.py", "manifest:...", "docs/..."],
    "reference_kinds": ["static"|"manifest"|"dynamic"|"doc"],
    "classification": "protected" | "candidate" | "unknown"
  }
```

**분류 규칙**

| 조건 | 분류 |
|---|---|
| 2절 불가침 목록에 해당 | `protected` |
| 참조 1건 이상 | `protected` |
| 참조 0건 + 같은 계열의 더 최신 세대가 존재 | `candidate` |
| 참조 0건 + 계열 판단 불가 | `unknown` |

**`unknown`은 이 라운드에서 손대지 않는다.** 보고만 한다.

**C0 게이트**

- [ ] `data/`·`outputs/`·`reports/` 전 파일이 정확히 한 분류를 가진다
- [ ] `protected` 안에 2절 불가침 목록이 **전부** 포함된다
- [ ] 매니페스트 전이 참조를 따라갔음을 근거와 함께 보고

### C1 — 세대 중복 확정

`candidate` 중에서 **같은 계열의 옛 세대**만 추린다.

계열 판정은 파일명에서 SHA를 제거한 접두사로 한다.

```
table_atomic_facts_arm1_embeddings_<SHA>.f32
  → 계열: table_atomic_facts_arm1_embeddings
```

계열별로 다음을 보고한다.

| 계열 | 세대 수 | protected 세대 | candidate 세대 | 회수 가능 용량 |
|---|---:|---|---|---:|

**C1 게이트**

- [ ] 각 계열에 `protected` 세대가 **최소 1개** 있다
      (0개면 그 계열 전체를 `unknown`으로 강등하고 손대지 않는다)
- [ ] 회수 가능 용량 합계를 보고

### C2 — 이동 (삭제 아님)

`candidate`로 확정된 것만 옮긴다.

```
<원래 경로>  →  archive/<원래 경로>
```

**규칙**

- `git mv` 를 쓴다. 내용 해시가 보존되어 되돌리기가 한 번에 된다
- `archive/` 를 `.gitignore` 에 넣지 **않는다**. 이 단계에서는 추적 유지
- 파일을 **삭제하지 않는다**. 이 라운드에 `rm` 은 없다
- 이동 전체를 **단일 커밋**으로 만든다. 되돌릴 때 `git revert` 한 번

**C2 게이트**

- [ ] `git status` 에 `deleted:` 가 **0건**
- [ ] 이동 목록이 C1 표와 정확히 일치

### C3 — 검증

**여기서만 Qwen 1회를 쓴다.**

1. 전체 회귀
   ```
   python -m pytest tests/v3 -q
   ```
   기준: **1,269 passed / 2 failed**. 실패 2건은 기존 면제 항목과
   **동일한 이름·동일한 실패 사유(SHA 불일치)** 여야 한다.
   사유가 `FileNotFoundError` 로 바뀌면 **즉시 C2 revert**.

2. 봉인 SHA 재확인
   ```
   product_free_rag_a6_frozen_...  → 9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc
   freeze_manifest_...             → 4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499
   ```

3. 런타임 스모크 — Product Free RAG로 **1문항** 실행 (Qwen 1회)
   ```
   질문: 해방의 계약은 가격과 이용 기간이 어떻게 되고, 구매하면 특별 보상으로 무엇을 한 번 받아?
   ```
   기준: `mode`가 `answer` 또는 `partial`, 인용 좌표 전부 정확,
   예외 없이 종료. **답 내용은 판정 대상이 아니다** (이 라운드는
   품질을 바꾸지 않으므로).

**C3 게이트 — 하나라도 실패하면 C2를 revert 하고 중단**

- [ ] 1,269 passed / 2 failed, 실패 사유 동일
- [ ] 봉인 SHA 2개 불변
- [ ] 스모크 1문항 정상 종료

### C4 — 클론 용량: 옵션만 제시, 실행 금지

C2를 해도 `.git` 163 MB 는 줄지 않는다. 선택지를 **표로 정리해 보고만
하고 아무것도 실행하지 않는다.** 사용자 결정 사항이다.

각 옵션에 대해 다음을 조사해 채운다.

| 옵션 | 예상 클론 용량 | 되돌리기 | 이력 보존 | 리스크 |
|---|---:|---|---|---|
| A. 그대로 두고 README에 안내 | | | | |
| B. 정리본만 새 저장소로 push | | | | |
| C. history rewrite (filter-repo) | | | | |

**B·C를 실행하지 말 것.** 특히 C는 커밋 SHA가 전부 바뀌어 지금까지의
모든 보고서에 적힌 커밋 해시가 무효가 된다 — 이 프로젝트에서는
치명적일 수 있다. 그 영향 범위를 조사해 보고에 포함한다.

---

## 4. 별도 항목 — 진입점 정리 (C2와 같은 커밋에 넣지 말 것)

용량과 무관하지만 첫인상에 가장 크게 작용한다. **별도 커밋**으로.

1. 최상위에 포트폴리오 문서가 2개다
   ```
   PORTFOLIO_REPORT.md
   PORTFOLIO_V3_DRAFT.md
   ```
   읽는 사람이 뭘 봐야 하는지 알 수 없다. 각각이 무엇이고 어느 쪽이
   최신인지 **조사해 보고만 한다.** 통합·삭제는 이 라운드에서 하지 않는다
   (포트폴리오 본문 작성 라운드에서 다룬다).

2. `README.md` 가 현재 수정 중(`M`) 상태다. 어떤 변경이 걸려 있는지,
   커밋해도 되는 상태인지 보고한다.

3. 미추적 677개의 처분 제안을 **분류별로** 제시한다. 실행하지 않는다.

   | 경로 | 개수 | 제안 | 근거 |
   |---|---:|---|---|
   | `reports/v3` | 313 | | |
   | `data/v3` | 106 | | |
   | `src/v3` | 93 | | |
   | `outputs/v3` | 83 | | |
   | `tests/v3` | 42 | | |
   | `docs/v3` | 28 | | |
   | `app/` | 5 | | |

   특히 `app/` 5개(`product_free_rag_api.py`, `product_free_rag_demo.py`,
   `product_free_rag_ui`, 그 외)는 **데모라서 포트폴리오 가치가 높다.**
   커밋 대상인지 우선 판단할 것.

---

## 5. 하지 말 것

- `rm` / `git rm` — 이 라운드에 삭제는 없다
- `.gitignore` 수정 — C2는 이동만 한다
- `git filter-repo` / `filter-branch` / force push
- 봉인 artifact 및 그 매니페스트 접근 (읽기 외)
- 파이프라인 코드 수정 — 이 라운드는 `src/v3/*.py` 의 **내용**을 바꾸지 않는다
  (미참조 스크립트도 이번엔 옮기지 않는다. 참조 그래프의 동적 경로
  탐지가 불완전할 수 있어 위험 대비 이득이 낮다)
- 평가 재실행 — C3 스모크 1회 외 Qwen 호출 금지
- C0~C4를 한 커밋에 묶기

---

## 6. 보고 양식

```markdown
## C0 참조 그래프
- 조사 파일 수:
- protected / candidate / unknown:
- 매니페스트 전이 참조 최대 깊이:
- 동적 경로로 구제된 파일 수:      ← 정적 조사만 했으면 놓쳤을 것
- 게이트: 통과 / 실패

## C1 세대 중복
| 계열 | 세대 | protected | candidate | 회수 MB |
- 회수 가능 합계:
- protected 세대 0개라 강등한 계열:

## C2 이동
- 이동 파일 수 / 용량:
- deleted 건수: (0이어야 함)
- 커밋:

## C3 검증
- pytest:            passed /  failed
- 실패 2건 사유 동일 여부:
- 봉인 SHA 2개:
- 스모크 mode / 인용 정확 / 예외:
- 게이트: 통과 / 실패

## C4 클론 용량 (조사만)
| 옵션 | 예상 용량 | 되돌리기 | 리스크 |
- 옵션 C가 무효화하는 커밋 해시가 적힌 문서 수:

## 별도 — 진입점
- PORTFOLIO 문서 2개 각각의 정체:
- README M 상태 내용:
- 미추적 677개 분류별 제안:
```

---

## 7. 결과별 분기 — 미리 정해두고 시작

| 결과 | 다음 |
|---|---|
| C0에서 `unknown` 이 candidate보다 많음 | 참조 탐지가 부실한 것. C1 중단하고 탐지 방법 보고 |
| C1 회수 가능 용량 < 50 MB | 이동 이득이 작다. C2 중단하고 보고만 |
| C3 회귀 실패 | C2 revert. 어느 파일이 필요했는지 특정해 보고 |
| C3 전부 통과 | 여기서 라운드 종료. 포트폴리오 본문 작성으로 넘어감 |

**어떤 경우에도 C4의 B·C를 실행하지 않는다.**

---

## 8. 이 라운드의 가치

숫자를 올리는 라운드가 아니다. 다음 두 가지를 만든다.

1. **참조 그래프** — 어떤 산출물이 살아 있고 어떤 게 죽었는지 처음으로
   증명된다. 이건 정리 여부와 무관하게 자산이다.
2. **되돌릴 수 있는 정리** — 삭제 없이 이동만 하므로, 잘못돼도 커밋
   하나를 revert 하면 원상복구된다.

정리 자체보다 **"봉인 무결성을 유지한 채 저장소를 정리한 절차"**가
포트폴리오 소재다. 그래서 삭제가 아니라 증명 → 이동 → 검증 순서다.
