# Product Free RAG 코퍼스 승격 결과 — 2026-08-11

## 결론

`product_free_rag_v1`만 2026-08-07 수집 후보로 전환했다. 연구·레거시
런타임의 기본 상수와 기존 봉인 artifact는 변경하지 않았다.

| 항목 | 승격 값 |
|---|---:|
| 문서 | 996 |
| 청크 | 3,925 |
| source coverage | 2026-08-07 |
| Product BM25 manifest | `9f1c64fe…17aa7` |
| Product dense manifest | `00070b49…3265` |
| Product chunk corpus | `45030e56…dcd7` |

현재 날짜는 2026-08-11이므로, 현재·진행 중 집합 질문은 2026-08-07까지
검증된 범위라는 경계를 계속 표시한다.

## 이전 롤백 원인 정정

이전 보고에서는 7월 월간 상품 revision이 새 후보에 보존되지 않았다고
판정했다. 재감사 결과 정답 본문은 공식 보관 문서
`https://df.nexon.com/community/news/seriashop/630`에 존재했다.

실제 원인은 `7월`처럼 연도가 없는 과거 월 질문이 현재 시점 정책을
그대로 사용해 `expired/default_exposure=false` 문서를 검색 전에 제외한
것이었다. Product 검색 정책에서 지난 월을 명시한 질문만 보관 상태를
열고, identity shortlist가 기준 연도의 월 구간을 대조하도록 수정했다.
도메인명·URL·아이템명 허용목록은 추가하지 않았다.

## 세로형 상품표 검증 수정

월간 상품표는 품목명이 `표 대상`에 있고 행의 첫 칸은
`상점판매가격`, `거래타입` 같은 속성이다. 기존 verifier는 첫 칸을
품목명으로 오해해 정답 claim을 `table_row_subject_mismatch`로 차단했다.

`표 대상`이 정확히 한 품목인 세로형 표에서는 그 품목을 행 주어로
사용하도록 수정했다. 여러 품목이 있는 표와 기존 형제 행 구분 규칙은
그대로 유지했다.

## 실답변 검증

### 미카엘라 보상 종류

- mode: `answer`
- 공식 라이브 가이드가 검색 1위
- 퍼스트 서버 인용: 0
- 서버 reward-kind 렌더링 사용
- rejected claim: 0

### 7월 스페셜 클론 레어 아바타 풀세트 상자

- mode: `answer`
- 상점판매가격: `4,000만 골드`
- 거래타입: `교환가능`
- 공식 7월 보관 문서가 검색 1위
- 두 claim 모두 원문 표 행 좌표로 복원
- rejected claim: 0

## 회귀

```text
python -m pytest tests/v3 -q
1,488 passed / 2 failed / 67 subtests passed
```

실패 두 건은 기존 봉인 manifest의 소스 SHA 불일치다.

- `test_retrieve_decomposed.py`
- `test_run_unified_runtime.py`

새 코퍼스·Product 런타임에 따른 기능 회귀 실패는 0건이며
`git diff --check`도 통과했다.

## 평가 경계와 남은 일

- 공식 sealed A6 `20/32`는 과거 봉인 실행이므로 변경하지 않는다.
- 새 코퍼스에 대한 adaptive A6 32문항 재실행은 이번 승격의 필수
  회귀가 아니며 아직 실행하지 않았다.
- `app/product_free_rag_api.py`, `app/ui/`의 병렬 UI·세션 변경은 이
  승격 범위와 분리한다.
- 미추적 shadow planner, collection-contract 및 대량 실험 산출물은
  Product 기본 경로에 포함하지 않는다.
