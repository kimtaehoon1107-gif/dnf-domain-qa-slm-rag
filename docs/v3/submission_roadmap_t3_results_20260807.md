# Submission Roadmap T3 실행 결과 — 2026-08-07

## 결론

T3 발표자료 제작 gate는 **PASS**다.

- 최종 파일: `docs/assets/dnf_official_qa_rag_portfolio_20260807.pptx`
- 슬라이드: 14장
- SHA-256: `0c7dc1ab3fbe64cbf9a3201e1cadd9b08d318f88e09d02a7fb9bc7a2e3717fe5`
- 외부 이미지: 없음
- 로컬 데모 캡처: `docs/assets/product_free_rag_demo_20260806.png` 1개
- 모델·GPU·Qwen 호출: 없음

## 전달하려는 한 문장

이 프로젝트의 가장 강한 결과는 높은 단일 점수가 아니라, 공식 문서 QA/RAG를 **재현 가능하게 측정하고 실패 지점을 검색·생성·검증으로 분리한 평가 체계**다.

## 구성

1. 문제와 핵심 수치
2. 문서 안 숫자도 조건을 잃으면 오답이 되는 사례
3. 검색 → 근거 압축 → 1회 생성 → 최소 검증 파이프라인
4. 발견·수집·동결을 분리한 데이터 구축
5. 표·시간 구조와 안정적 근거 좌표
6. OCR 격리 근거
7. contract → seal → one-shot 평가 절차
8. hybrid 검색 결과와 채택하지 않은 실험
9. SLM → typed contract → Product Free RAG 방향 전환
10. 남은 실패의 위치
11. 공식 A6 결과와 데모
12. 코퍼스 갱신 운영 계약

## 검증

| 항목 | 결과 |
|---|---:|
| 렌더링 | 14/14 성공 |
| 원본 크기 시각 검수 | 14/14 완료 |
| 슬라이드 overflow 검사 | 0건 |
| `[Sources]` speaker notes | 14/14 |
| T2 검증 ledger 밖의 수치 | 0건 |
| 잘린 제목·표·차트·스크린샷 | 0건 |

숫자는 T2에서 대조한 `PORTFOLIO.md`와 원본 manifest/report만 사용했다. 특히 다음 수치를 서로 다른 벤치마크로 유지했다.

- typed sealed: 37/64
- Product A6 sealed 자동 채점: 7/32
- Product A6 sealed 사람 감수: 20/32
- 코퍼스: 2026-07-17 · 문서 980 · 청크 3,599

## 재현 메모

- Codex Grid 계열의 흰색·검정·파랑 시각 체계를 사용했다.
- 최종 PPTX를 다시 렌더링한 뒤 `slides_test.py`로 검사했다.
- 한글 경로에서 렌더러의 Windows 기본 인코딩 문제가 있어, 검수용 복사본만 ASCII 임시 경로에서 UTF-8 환경으로 렌더링했다. 최종 PPTX의 위치와 내용은 바꾸지 않았다.
- 생성 과정의 inspect sidecar와 렌더 PNG는 `tmp/`에만 두며 제출 파일에는 포함하지 않는다.

## 판정

T3는 완료됐다. 다음 단계는 T4가 아니라, 충돌 금지 범위인 `app/`을 건드리지 않고 T5 코퍼스 갱신 gate를 GPU 사전 점검부터 수행하는 것이다.
