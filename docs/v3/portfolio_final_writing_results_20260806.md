# 최종 포트폴리오 작성 결과 — 2026-08-06

## 산출물

- `PORTFOLIO.md` 줄 수 / 최상위 절 수: **371줄 / 12절**
- 기존 문서 2개 안내 줄 추가: **완료**
  - `PORTFOLIO_REPORT.md`: v2 실험 기록 안내
  - `PORTFOLIO_V3_DRAFT.md`: typed v3 실험 기록 안내
- `README.md`: 이번 라운드에서 수정하지 않음
- Product Free RAG 데모 스크린샷: `docs/assets/product_free_rag_demo_20260806.png`

## 숫자 검증

- §3-A 사용 건수: **14개 항목**
  - 공식 sealed A6 표 12개 항목 전부
  - 마지막 회귀 기록 1개
  - A6-7 근거 좌표 1개
- §3-B 재확인 시도 / 성공 / 본문 제외: **7 / 6 / 2**

| 값 | 재확인 경로 | 결과 |
|---|---|---|
| adaptive 사람 감수 24/32 | `reports/v3/product_free_rag_pending_apply_and_adaptive_replay_20260806.md` | 확인, adaptive 라벨로 사용 |
| 요구 단위 재도출 43/57 | 지시서와 관련 보고서 검색 | 단독 authoritative derivation을 확인하지 못해 제외 |
| 통제 지연 p50 7.528 / p95 11.579 / max 25.161 / 초과 0/50 | `reports/v3/product_free_rag_latency_gate_and_controlled_remeasure_20260805.md`와 원시 JSONL | 확인, adaptive 통제 진단으로 사용 |
| typed sealed 37/64 | `reports/v3/typed_evidence_ref_generalization_64_relation_group_currency_v2.json`의 `sealed_result_preserved` | 확인, sealed 라벨로 사용 |
| typed adaptive 55/64·56/64·49/64·44/64 | `reports/v3/typed_evidence_ref_claim_contract_round_20260727.md` 등 원 보고서 | 출처는 확인했으나 2막 압축과 sealed/adaptive 혼동 방지를 위해 제외 |
| explicit relation contract 22/96 | `reports/v3/typed_evidence_ref_relation_inventory_96_20260727.json` | 확인, adaptive contract audit로 사용 |
| v2 3축 비교 | `PORTFOLIO_REPORT.md` §7과 `reports/final_dev_system_comparison.json` | 확인, adaptive development evaluation으로 사용 |

- artifact 근거 없이 쓴 결과 수치: **0**
- 코드 파라미터 근거:
  - hybrid depth·weight: `src/v3/retrieve_v3.py`
  - 후보·parent·pack·token 상수: `src/v3/product_free_rag.py`
  - reranker 모델·revision: `src/v3/score_evidence_reranker.py`
- 코퍼스 수치 근거:
  - `data/v3/runtime/free_minimal_runtime_snapshot_v1.json`
  - normalized / chunk / retrieval-clean manifest

## 데모

- 실행 결과: **정상**
  - Gradio `product_free_rag_v1` 선택 화면을 `127.0.0.1:7861`에서 로드
  - 질문 제출 없음, Qwen 호출 0
  - FastAPI `health()` 응답: `status=ok`, `runtime_loaded=False`
- 커밋 여부: **완료**
  - commit `410afae` — `Add local Product Free RAG demo`
- 데모 프로세스: 확인 후 종료

## 게이트

| 게이트 | 결과 | 증거 |
|---|---|---|
| 모든 수치의 §3-A 또는 artifact 근거 | 통과 | 위 숫자 검증표와 본문 25개 로컬 링크 |
| sealed / adaptive와 자동 / 사람 판정 분리 | 통과 | 헤드라인·각 결과 절에 역할 라벨 표기 |
| 37/64와 20/32 우열 비교 금지 | 통과 | 서로 다른 비중복 벤치마크·난이도 미통제를 명시하고 우열 문장 없음 |
| §3-B 재확인 실패값 제외 | 통과 | 43/57 제외, typed adaptive 계열도 본문에서 제외 |
| 봉인 SHA 2개 불변 | 통과 | frozen `940540...65dc`, manifest `4d47ef...8499` 실제 파일 SHA 재계산 일치 |
| README·회귀 기준 보존 | 통과 | README diff hash 전후 `91c64a4f521dfbdeb5ad7247ea753614030ba91a`; 마지막 회귀 1,269 passed / 기존 면제 2 failed |
| 데모 실행 확인과 스크린샷 | 통과 | Gradio 로드, API health, PNG 51,013 bytes, 데모 커밋 완료 |
| 코퍼스 스냅샷·chunk ID·무변경 | 통과 | 날짜·980/3,599·갱신 절차·`build_chunks.py:124` 포함; 지정 4개 데이터 디렉터리 `git status` 출력 없음 |

추가 구조 감사:

- `PORTFOLIO.md` 최상위 `##` 절: 계획과 일치하는 12개
- 내부 Markdown 링크: 25개, 누락 경로 0
- `PORTFOLIO_REPORT.md` 본문 변경: 안내 2줄만 추가
- `PORTFOLIO_V3_DRAFT.md`에는 안내 2줄만 새로 추가했으며, 나머지 기존 사용자 변경은 보존
- 코퍼스 수집·정규화·청킹·인덱스 재빌드: 실행하지 않음
- 평가 재실행·재채점·Qwen 호출: 0

## 남은 것

- 다음 라운드로 넘긴 항목:
  - 2026-07-17 이후 공식 문서 코퍼스 갱신
  - 기존 chunk ID 유지율 측정
  - 검색 순위 변동 측정
  - 공개 adaptive 질문의 답 변화 진단
  - 새로운 사람 검수 봉인 세트 설계·1회 실행

이 항목들은 결과가 없으므로 포트폴리오에 예상 수치를 쓰지 않았다.
