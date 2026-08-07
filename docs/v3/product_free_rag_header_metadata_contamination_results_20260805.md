# Product Free RAG 헤더 메타데이터 오염 실험 결과 — 2026-08-05

## 결론

헤더 게시 시각과 조회수 atomic unit을 런타임에서 제외했다. 코퍼스와
`display_text`, `chunk_id`, offset 좌표는 변경하지 않았다.

저장 출력 전수 스캔에서 게시 시각 자체를 묻는 정상 질문이 발견되어,
도메인명 하드코딩 없이 질문이 게시·게재·등록·공지의 시점/시각/시간/날짜를
명시적으로 요구할 때만 게시 타임스탬프를 유지한다. 조회수 헤더 unit은
계속 제외한다.

이 보정 후 A6-2는 `14시`에서 본문 정답 `15시`로 복구됐고, 확인된 악화는
0건이다.

## 지연 기준선

| 실행 | p50 | p95 | 최대 | 비고 |
|---|---:|---:|---:|---|
| 기존 hook ON | 22.56초 | 43.04초 | 43.04초 | 기존 보고값 |
| 변경 전 hook OFF | 11.308초 | 101.201초 | 101.201초 | 10문항, 답변 오류 0 |
| 변경 후 hook OFF | 10.544초 | 28.780초 | 28.780초 | 10문항, 답변 오류 0 |

변경 전 hook OFF의 p95는 slot 3·4 candidate rerank 이상 지연 때문에 커졌다.
변경 후 감소는 헤더 필터의 성능 개선으로 귀속하지 않고 런 간 변동으로
판정한다. 관측 hook만이 기존 지연의 유일한 원인이라는 가설도 기각한다.

## 헤더 필터

- 헤더 청크: 502개
- 게시 타임스탬프: 502개
- 조회수 줄: 410개
- A6 골드 좌표: 62개
- 변경 전/후 pack 진입 벡터: 동일(55/62 visible)
- chunk corpus SHA-256: 변경 없음
- A6 post pack 좌표 원문 복원: 32/32
- A6-2 pack: 헤더 `2025.08.12 14:00` 제거, 본문 `8월 12일 15시`가 E1
- A6-2 라이브: `15시`, `8월 13일`, 두 claim 모두 본문 좌표 인용

## 저장 출력 전수 스캔

- JSONL 파일: 310개
- 답변 record: 1,309개
- 필터의 실제 제거 대상 헤더를 인용한 record: 8개
- 고유 질문: 2개
- Qwen 호출: 0회

사람 판정:

| 분류 | record | 고유 질문 | 내용 |
|---|---:|---:|---|
| 개선 | 3 | 1 | A6-2의 게시 `14:00`을 시작 시각으로 오인 |
| 악화 | 0 | 0 | 없음 |
| 불변 | 5 | 1 | 원격지원 휴무 claim은 본문 `7/17(금) 제헌절` 근거가 별도로 존재 |

초기 무조건 필터 스캔에서 발견된 게시 시각 질문 8 record와 공지 시점 질문
2 record는 일반적인 질문 역할 예외로 게시 타임스탬프를 유지한다.

## USER10 v2 라이브

- 10/10 mode 동일
- 10/10 최종 답변 문자열 동일
- 오류 0
- post mode: answer 6, unsupported 4
- 라이브 Qwen 호출: 변경 전 기준선 10회, A6-2 1회, 변경 후 USER10 10회

## 테스트

- 헤더 진단·필터·스캔 단위 테스트: 9 passed
- Product Free RAG 관련 회귀: 157 passed
- 전체 `tests/v3`: 1,216 passed, 2 failed, 67 subtests passed

전체 스위트의 실패 2건은 이번 코드 경로와 무관한 별도 content-addressed
frozen manifest SHA drift다.

1. `test_retrieve_decomposed.py`의 decomposed hybrid manifest SHA 불일치
2. `test_run_unified_runtime.py`의 unified runtime manifest SHA 불일치

이번 변경에서 frozen manifest를 재생성하거나 기대 SHA를 수정하지 않았다.

## 판정

헤더 필터 기능은 GO다. A6-2 복구, 저장 출력 악화 0, USER10 불변,
좌표 32/32, corpus SHA 불변을 만족했다. 다만 저장소 전체 release gate는
위의 별도 frozen manifest drift 2건을 감사하기 전까지 완전 green으로
표현하지 않는다.
