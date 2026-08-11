# DNF 공식 문서 QA/RAG

던전앤파이터 공식 문서에서 답을 찾고 근거 좌표까지 복원하며, 봉인 평가와 사람 감수로 실패를 추적한 로컬 QA/RAG 프로젝트입니다.

> **포트폴리오 본문: [PORTFOLIO.md](PORTFOLIO.md)**

## 현재 상태

| 무엇을 만들었나 | 현재 구성 | 범위 |
|---|---|---|
| 공식 문서 QA/RAG | BM25 + BGE-M3 → BGE reranker → atomic evidence pack → 조건부 서버 렌더링 또는 Qwen3 8B 1회 → bounded verifier → 서버 인용·표 복원 | 무료·로컬 실행 |
| 평가 체계 | 봉인 세트, SHA 동결, 1회 실행, 사람 근거 검수, adaptive 진단 분리 | 성능보다 측정 정직성 우선 |

| 시스템·평가 | 최종 숫자 | 해석 |
|---|---:|---|
| v3 typed, **sealed** | **37/64** | 타입 계약 시스템의 공식 봉인 결과 |
| Product Free RAG A6, **sealed 자동 채점** | **7/32 (21.9%)** | 표면값 중심 자동 채점 결과 |
| Product Free RAG A6, **sealed 사람 감수** | **20/32 (62.5%)** | 봉인 출력을 근거와 대조해 확정한 공식 결과 |
| 숫자 해석 제한 | 비교 금지 | 64문항과 32문항은 서로 겹치지 않는 다른 벤치마크이며 난이도도 통제되지 않았습니다. 어느 시스템이 더 낫다는 비교에는 사용할 수 없습니다. |

| 판정 대상 | 판정 | 이유 |
|---|---|---|
| 포트폴리오 공개 | **GO** | 성공뿐 아니라 실패, 측정 오류, 기각한 개선안까지 재현 가능하게 남겼습니다. |
| Product Free RAG 제품 기본 경로 승격 | **NO-GO** | A6 사람 감수 정확도가 목표 80%에 미달하고 한 건의 unsupported overclaim이 남았습니다. |

## 코퍼스 스냅샷

```text
코퍼스 스냅샷   2026-08-07 수집·정규화 · 검색용 청크 확정
규모            문서 996 · 청크 3,925
갱신 절차       discover_sources → collect_details → 정규화 → 청킹
                → BM25 재빌드 → dense 재임베딩
```

2026-08-11 재감사에서 7월 공식 보관 revision을 확인하고 `product_free_rag_v1`만 새 스냅샷으로 승격했습니다. 연구·레거시 기본 런타임과 봉인 artifact는 유지했으며, 과정은 [승격 결과](reports/v3/product_free_rag_corpus_promotion_20260811.md)에 기록했습니다.

## 문서 안내

| 문서 | 언제 |
|---|---|
| [PORTFOLIO.md](PORTFOLIO.md) | 프로젝트 전체와 Product Free RAG 재현 방법을 보고 싶을 때 |
| [PORTFOLIO_V3_DRAFT.md](PORTFOLIO_V3_DRAFT.md) | v3 typed 파이프라인 상세를 보고 싶을 때 |
| [PORTFOLIO_REPORT.md](PORTFOLIO_REPORT.md) | v1/v2 SLM 파인튜닝 기록을 보고 싶을 때 |
| [docs/v3/](docs/v3/) | 라운드별 지시서·계약을 확인할 때 |
| [reports/v3/](reports/v3/) | 실행 결과 artifact를 확인할 때 |
| [docs/legacy_v1_v2_reproduction.md](docs/legacy_v1_v2_reproduction.md) | v1/v2 실험의 재현 커맨드가 필요할 때 |

## 직접 검증하기 (모델·GPU 불필요)

```bash
git -c core.longpaths=true clone https://github.com/kimtaehoon1107-gif/dnf-domain-qa-slm-rag
git -C dnf-domain-qa-slm-rag config core.longpaths true
cd dnf-domain-qa-slm-rag
pip install -r requirements.txt
python -m pytest tests/v3 -q
```

2026-08-11의 새 클론 재검증 결과는
`1,364 passed / 2 failed / 67 subtests passed`입니다.

실패 2건은 동결 artifact와 현재 재생성 manifest의 SHA가 다른 기존 known
failures입니다. 새 Product 변경의 회귀와 구분해 그대로 보고합니다. 테스트는 생성
모델을 모킹하므로 **Ollama·GPU·모델 다운로드·인터넷이 모두 필요 없습니다.**

첫 두 줄은 긴 artifact 경로가 있는 Windows 저장소를 위한 설정입니다. Linux·macOS는
일반 `git clone`도 사용할 수 있습니다. 독립 검토의 전체 범위와 발견한 false-full
수정은 [평가자 재검토 보고서](reports/v3/independent_evaluator_review_20260811.md)에
남겼습니다.

실제로 질문을 던져보려면 [PORTFOLIO.md §11](PORTFOLIO.md#11-기술-스택과-재현)의
데모 실행 절차를 참고하세요. 이 경우에는 Ollama와 약 10 GB의 모델이 필요합니다.

## Data Source Notice

The documents under `data/` are collected from the official Dungeon & Fighter
website operated by Neople. All game content and original document text are the
property of Neople Inc. They are included here solely for non-commercial
research and educational purposes (document-grounded QA evaluation). If you are
a rights holder and want any content removed, please open an issue.
