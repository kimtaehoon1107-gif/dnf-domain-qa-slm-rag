# Submission roadmap T2 결과 — 포트폴리오 데이터·검색·평가 재구성

## 범위

- `PORTFOLIO.md`를 12절 구조로 재구성했다.
- 새 §3 데이터 구축, §4 검색과 근거 선별, §5 평가 설계를 추가했다.
- 기존 SLM·typed·Product·실패·측정·재현·한계 절은 §6~§12로 이동했다.
- README와 레거시 재현 문서의 포트폴리오 앵커를 §11로 갱신했다.
- sealed artifact, 코퍼스, 인덱스, `app/`, `tmp/`는 수정하지 않았다.

## 수치 검증 원장

| 본문 주장 | 읽은 원본 | 재검증 결과 |
|---|---|---|
| 스냅샷 2026-07-17, 문서 980 | `data/v3/normalized/normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json` | 일치 |
| 청크 3,599 | `data/v3/chunks/chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json` | 일치 |
| `/pg/` 19개, visual evidence 5개 | canonical normalized contents의 `canonical_url`·`visual_evidence` 전수 집계 | 19, 5 |
| `/pg/` 검색 본문 362~29,841자 | 비-OCR 청크의 `retrieval_text`를 parent별 합산 | `aradfishing=362`, `tropicalpkg=29,841` |
| DOM/OCR 오탈자 표 | 원시 3,599 청크를 `chunk_type=visual_ocr` 여부로 분리해 `retrieval_text` exact occurrence 집계 | 120/4, 0/5, 2,432/9, 0/8, 157/4, 0/2 모두 일치 |
| visual OCR 22/3,599 및 격리 필드 | 원시 청크 전수 집계와 visual OCR 행 필드 검사 | 22, `unverified_ocr`, `review_required=true`, `default_exposure=false` |
| hybrid 0.75/0.25 결과 | `docs/v3/hybrid_fusion_contract.md`와 frozen grid report | 본문 네 지표 일치 |
| reranker 네 arm | `reports/v3/evidence_reranker_ab_763ca7b93bec87e475a4406f24b7780ebaeadffb7a36b494c473452244d8c90f.json` | 표 네 행 일치 |
| federated NO-GO | `reports/v3/federated_retrieval_ab_0e48bfbc2d69d6b524b98b83c79d0ff296540ba05374e72cd1ec6f0616a5172c.json` | baseline 73/82·9/82, arms 63/82·18~19/82 |
| requirement retrieval NO-GO | `reports/v3/requirement_retrieval_ab_ff945c4b87b691b248ced8a3541ba53cd025f41183dd03de5dddf00ae8b45cd9.json` | recovery 0/7, arms 64/82·18/82와 63/82·19/82 |
| claim-aware reranker | `reports/v3/claim_reranker_runtime_f37db5f17f3d20553d14922471c5bf7415ff942b12746dfad6d831a6a0ef1df9.json` | 47→56, strict mismatch 3, production NO-GO |
| corpus hygiene NO-GO | `reports/v3/corpus_hygiene_remeasurement_7cd274672459e64f083f90bae819729a6f43515e17ed476e3d25e473012708c4.json` | 560/3,599, 73→72, 9→10 |
| `docs/v3/` 계약·진단 137개 | `git ls-files docs/v3` | 137 |
| A6 frozen·manifest SHA | frozen 파일 bytes와 freeze manifest | `9405401d…65dc`, `4d47ef5d…8499` 일치 |
| 회귀 | 격리된 offline 환경의 실제 `pytest tests/v3 -q` | 1,269 passed / 기존 SHA 면제 2 failed |

검증하지 못한 채 본문에 넣은 숫자는 **0개**다. 이 표의 OCR 빈도는 normalized DOM 문자열 빈도가 아니라 검색에 실제 투입될 청크 `retrieval_text`를 OCR/non-OCR로 나눈 값이다.

## 구조·링크 게이트

- `PORTFOLIO.md`: 433줄
- 새 §3: 35줄
- 새 §4: 32줄
- 새 §5: 23줄
- 12개 번호 절과 부록 A/B: 존재
- fenced code를 제외한 `PORTFOLIO.md#...` 링크: 2개, 깨진 앵커 0개
- T2 전달 파일의 로컬 Markdown 링크: 깨진 링크 0개

## 판정

수치·분량·링크 gate를 통과했다. git diff 감사를 마친 뒤 T2를 별도 커밋한다.
