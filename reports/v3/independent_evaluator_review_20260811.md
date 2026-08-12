# Product Free RAG 독립 평가자 재검토 — 2026-08-11

## 1. 검토 원칙

기존 README·PORTFOLIO·라운드별 결론을 성능 근거로 먼저 읽지 않았다. 시작 커밋
`f852ee9`의 추적 파일만 새로 클론한 뒤 코드, 런타임 스냅샷, 테스트, 실제 질문
출력을 순서대로 확인했다. 기존 문서는 기술 검토가 끝난 뒤 주장과 실측을 대조하는
용도로만 사용했다.

## 2. 독립 확인 범위

- Product 경로가 typed ClaimSpec planner·relation registry·typed verifier를 import하지
  않는지 확인
- BM25·dense 검색 깊이, reranker 깊이, parent 제한, evidence pack 상한 확인
- Product 런타임 스냅샷이 가리키는 artifact 8개의 존재와 SHA-256 전수 확인
- 새 클론에서 전체 `tests/v3` 실행
- 대표 질문 9개를 실제 BGE-M3·reranker·Qwen3 8B 또는 서버 렌더러까지 실행
- 별도 미커밋 로컬 API/UI 트랙에서 질문 제출, 답변·인용 카드·정적 이미지 로드
  확인. 이 UI 변경은 제출 재현 범위와 커밋에 포함하지 않음

## 3. 확인된 현재 구조

```text
질문 정규화
→ 집합 연산 질문이면 metadata 경로
→ 그 외 전체 질문 + 요구 절별 BM25 20 / BGE-M3 20
→ 후보 union + BGE reranker
→ top 8, parent당 최대 2개
→ atomic evidence pack 최대 8개
→ 구조가 충분한 비교·종류·보상 표면 서버 결정 렌더링
→ 나머지만 Qwen3 8B 한 번
→ bounded deterministic verifier
→ 서버 인용 좌표·원문 표 복원
```

제품 경로에 도메인명·레이드명·아이템명 허용목록은 없었다. 한국어 질문 의미를
다루는 일반 어휘·정규식은 상당량 존재한다. 또한 `product_minimal_verifier.py`는
약 2천 줄이므로 현재 구현을 “네 가지 검사만 하는 최소 verifier”라고 부르는 것은
정확하지 않다. 역사적 모듈명은 유지하되 포트폴리오에서는 **bounded deterministic
verifier**로 기술한다.

## 4. 코퍼스·인덱스 무결성

Product 런타임 스냅샷은 문서 996개·청크 3,925개를 가리킨다. documents, chunks,
BM25 manifest, dense manifest, source registry와 두 corpus manifest까지 8개 artifact의
파일 SHA가 스냅샷 값과 모두 일치했다. dense manifest는 `BAAI/bge-m3`, 1024차원,
normalized cosine이며 BM25와 같은 3,925개 청크를 사용한다.

상태 분포는 `current 888 · superseded 52 · expired 52 · unknown 4`다. event·notice·
update 수집 범위는 2026-08-07까지로 명시돼 있어, 2026-08-11의 “현재” 질문에는
범위 제한을 표시하는 것이 정상 동작이다.

## 5. 대표 질문 실제 실행

| 질문 유형 | 관찰 |
|---|---|
| 단일 입장 명성 | `최후의 과업 108,921`을 인용과 함께 답함 |
| 복수 대상 | `최후의 과업 108,921`, `디레지에 63,257`을 함께 답함 |
| 미카엘라 보상 종류 | 정식 가이드 근거의 서버 렌더링, Qwen 0회 |
| 미카엘라 난이도 종류 | 싱글·매칭·일반·하드, 서버 렌더링과 인용 정상 |
| 제작 재료 오타 | 일부 근거만 남긴 `partial`; 오결속 claim은 차단 |
| 모호한 디레지에 보상 | 안전하게 clarification, 다만 선택지 관련성은 개선 여지 |
| 오늘 날씨 | unsupported지만 Qwen을 호출해 불필요한 지연 발생 |
| 현재 이벤트 | metadata `partial`, 2026-08-07 coverage 제한을 명시 |
| 7월 월간 상품 | 수정 전에는 거래 타입 행의 `교환가능`을 판매가로도 노출한 false-full 발견 |

마지막 사례는 검색이나 인용 좌표 오류가 아니었다. Qwen이 같은 세로형 표에서
`거래타입` 행을 인용해 “상점판매가는 교환가능”이라고 썼고, 기존 verifier가 값의
존재만 보고 이를 허용했다.

## 6. 검토 중 수정

세로형 2열 표에 단일 대상이 명시된 경우, claim이 인용한 행의 첫 셀 관계명과
표면상 결속되는지 추가 확인했다. 수정 전 재현 테스트는 실패했고, 수정 후 같은 실제
출력에서 잘못된 판매가 claim은 `table_row_relation_mismatch`로 제거됐다. 올바른
거래 타입만 남아 최종 mode는 `partial`이 됐다. 즉 가용성을 과장하지 않으면서
false-full을 제거했다.

API도 데모와 동일하게 표 비교 예약과 availability·content-kind·reward-kind 서버
렌더러를 사용하도록 네 옵션을 맞췄다. 런타임 스냅샷의 경로와 모든 artifact SHA를
검사하는 회귀 테스트도 추가했다.

수정 커밋은 `efb995e`다.

## 7. 새 클론 재현 결과

짧은 경로 `C:\r\efb995e`에 추적 파일만 새로 클론해 실행했다.

```text
python -m pytest tests/v3 -q
→ 1,362 passed / 2 failed / 67 subtests passed
```

두 실패는 이번 변경과 무관한 기존 content-addressed manifest SHA 불일치다.

- `tests/v3/test_retrieve_decomposed.py`
- `tests/v3/test_run_unified_runtime.py`

작업 폴더에서는 미추적 실험 테스트까지 포함돼 1,506 passed가 나왔지만, 새 클론에서
재현되지 않으므로 포트폴리오 수치로 사용하지 않는다.

## 8. Windows 경로 재현성

일반 설정으로 깊은 OneDrive 경로에 clone하면 추적된 긴 artifact 경로 5개가 Windows
경로 제한에 걸렸다. 같은 위치에 아래 설정을 사용한 clone은 성공했고, 설정 적용 후
작업 트리도 깨끗했다.

```powershell
git -c core.longpaths=true clone <repository-url> dnf-domain-qa-slm-rag
git -C dnf-domain-qa-slm-rag config core.longpaths true
```

artifact를 옮기면 봉인 manifest와 내부 SHA 참조가 연쇄 변경되므로 이번 라운드에서
경로를 강제로 짧게 바꾸지 않았다. Windows 재현 절차에 위 전제조건을 명시한다.

## 9. 최종 판정

**포트폴리오 공개: GO.** 구조, artifact 무결성, 실패 사례, 안전 차단, 새 클론 테스트를
재현 가능하게 제시할 수 있다.

**제품 기본 경로 승격: NO-GO 유지.** sealed 사람 감수 20/32라는 공식 기준선은
바뀌지 않았고, clarification 품질·out-of-domain 선차단·세로형 표 관계의 완전한 답변
가용성·warm tail latency는 후속 과제다. 이번 재검토 결과를 새 공식 정확도 점수로
부르지 않는다.
