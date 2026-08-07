# Simple RAG Frozen B1+B3+B4 untouched32 one-shot

작성일: 2026-07-28

## 결론

새로 검수·봉인한 32문항에서 Frozen B1+B3+B4 후보는 **NO-GO**다.

| Arm | 사람 의미 완전 정답 | 실제 false-full | 안전하지 않은 partial | 생성 오류 |
|---|---:|---:|---:|---:|
| A1~A3 baseline | 15/32 (46.9%) | 0 | 1 | 1 |
| Frozen B1+B3+B4 | **16/32 (50.0%)** | **1** | 0 | 1 |

Frozen 후보는 24번을 올바른 partial로 복구해 완전 정답을 1건 늘렸다. 하지만
27번에서 질문과 다른 두 형제 상품의 구성품을 full answer로 노출했다. 사전 기준인
실제 false-full 0과 생성 오류 0을 모두 만족하지 못하므로 승격할 수 없다.

이 결과는 parent-document blind가 아니라, 새 질문·claim을 사람 검수 후 처음 실행한
untouched one-shot이다. 결과를 본 뒤 이 32문항에 맞춘 규칙을 추가하거나 재실행하지
않는다.

## 동결 조건

```text
모델: qwen3-8b:ctx8192
검색: subject/source-aware simple RAG
      → BM25 + BGE-M3
      → BGE reranker top 5
공통 안전장치: A1 subject-period identity
              + A2 relation-value colocation
              + A3 explicit temporal conflict

Arm A: 공통 안전장치까지
Arm B: Arm A + B1 table identity
             + B3 unique whitespace quote recovery
             + B4 normalized factual verification
```

- 후보 SHA: `2a131c3425e2c8d7affc848ab5b335d31173aa6fd01f73f985b5e851157a718a`
- 봉인 SHA: `6b2bc67087d255af1b4cfdc9076b8dfd8d0cce2b2194e2e2210af08eb8a95198`
- 실행 결과 SHA: `491c575468072f65581d47ae89f29f55ff54f5f70a266244a9167ad319ec3c06`
- 검색 호출: 32
- 생성 성공: 31/32
- 인용 좌표 검사: 32/32 exact
- 입력/출력 토큰: 113,377 / 8,092
- 생성 시간 mean/p50/p95: 30.97초 / 27.66초 / 46.62초
- 전체 파이프라인 mean/p95: 46.86초 / 74.66초

## 자동 점수와 사람 검수

| 지표 | A1~A3 | Frozen B1+B3+B4 |
|---|---:|---:|
| 자동 gold value complete | 11/32 | 12/32 |
| 자동 typed claim complete | 9/32 | 9/32 |
| 자동 semantic false-full flag | 5 | 6 |
| 사람 의미 완전 정답 | 15/32 | 16/32 |
| 사람 확인 실제 false-full | 0 | 1 |

자동 false-full에는 내용이 맞지만 문자열·골드 근거가 다른 12·13·14·17·30번이
포함된다. 사람 검수에서 확인된 실제 false-full은 Frozen 27번 한 건이다.

검색 후보는 strict gold 청크 기준으로는 `19/32`지만, 동등 공식 근거와
partial 문항의 지원 요구만 반영하면 내용상 `25/32`에 필요한 근거가 있었다.
내용상 검색·identity 누락은 3·7·23·25·26·27·28번이다.

## 핵심 실패

### 1번 — 생성 오류

정답 후보는 모두 있었다. 하지만 Qwen이 구조화 답변을 내지 않고 출력 한도
4,000토큰을 전부 소진했다. 재시도 없이 abstain으로 기록했다.

### 10·20·32번 — verifier overreject

- 10번: 모델이 이벤트 기간을 정확히 선택했지만 인용 문자열이 원문과 연속 일치하지 않았다.
- 20번: 두 칼레이도 박스의 값은 맞았지만 요약형 인용이라 모두 차단됐다.
- 32번: 거래 타입 `교환가능`과 구매 제한 unsupported를 정확히 생성했지만,
  과거 5월 상품에 current temporal 정책을 적용해 정상 값을 차단했다.

### 11번 — 교체 문항

우편 보관 기간 `15일`은 맞게 답했다. 하루 기준은
`매일 오전 06시 - 다음날 오전 06시` 대신 `1일`을 선택했다. verifier가 이 요구를
차단해 partial로 남았으므로 false-full은 아니다.

### 21·22번 — 요구사항 이탈

- 21번은 휴면ID의 `12개월`을 묻는데 현재 운영정책 버전과 시행일을 답했다.
- 22번은 비정상 재화 회수 여부를 묻는데 비인가 프로그램 제재를 답했다.

두 답변 모두 근거 복사 검사를 통과하지 못해 사용자에게 노출되지는 않았다.

### 24번 — 유효한 복구

B3가 공백 차이만 있는 공식 근거를 유일하게 복원했다. 길드장 권한 위임 조건은
정확히 답하고 문서에 없는 처리 기간은 unsupported로 유지했다.

### 27번 — 실제 false-full

질문은 `2026 DNF 폴리스 아바타 콤보 상자`를 물었다. 정답 후보가 없었는데
검색에는 가격이 같은 아래 형제 상품만 들어왔다.

```text
2026 나비 무도회 아바타 콤보 상자
2026 아라드 패스 웨딩 아바타 콤보 상자
```

Qwen은 두 상품의 구성품을 합쳐 답했고, B3가 그 인용을 원문으로 복원했다.
B1은 비표 상품 설명의 canonical product identity를 검사하지 않으며, B4는 값이
선택 근거에 존재하는지만 확인한다. 그 결과 잘못된 구성품을 full answer로
노출했다.

## 판단

Frozen B1+B3+B4는 adaptive 32에서 `22/32, false-full 0`이었지만 untouched에서는
`16/32, false-full 1`로 재현되지 않았다. 특히 B3의 quote recovery는 올바른 24번을
살리는 동시에 잘못된 형제 상품 27번도 살렸다. 따라서 B1+B3+B4를 현재 제품
기본값으로 승격하지 않는다.

다음 단계는 이 32문항에 맞춘 패치를 추가하는 것이 아니다. 포트폴리오에는 아래
세 결과를 함께 제시하는 편이 정직하다.

1. adaptive: `22/32`, 실제 false-full 0
2. untouched one-shot: `16/32`, 실제 false-full 1, 생성 오류 1
3. 원인: 검색 누락 7건과 비표 canonical product identity 부재, exact-quote
   verifier overreject, Qwen 요구사항 이탈

케이스 JSONL의 행별 `evaluation_role`은 기존 runner 상수로 남아 있지만, 봉인
manifest와 자동 summary의 untouched one-shot 역할이 권위 있는 값이다. one-shot
결과 행은 실행 후 수정하지 않았다.
