# Requirement surface-query canary packet refreeze amendment

## 상태

초기 authored packet의 사용자 전수 검수 결과는 24 승인, 8 기각이었다. 초기 packet,
manifest, report와 검수 결과는 삭제하거나 덮어쓰지 않는다. 이 문서는 기각 원인만 교정해
새 content-addressed packet을 만드는 보충 계약이다.

## 허용된 변경

- 3-requirement control 네 건의 목적격 조사 자동 선택
- 세리아샵 세 행의 table atomic value-cell evidence와 offset locator
- 최후의 조율자 두 행의 질문을 2026-03-26 패치로 한정
- packet 생성 시 조사, distinct span, current-document duplicate, expected action 불변식 추가

그 외 24개 승인 행의 `question_text`, `requirements`, `evidence_groups`, `gold_answer`,
`gold_chunk_ids`, `gold_document_ids`는 이전 packet과 동일해야 한다.

## 별도 기록

`question_decomposer.py`의 하위질의 조사 조립은 현재 Gradio 실행 경로 밖이며 프로즌 입력의
재현성에 영향을 주므로 이번 변경에서 제외한다. 후속 비실행 경로 정리 이슈로만 남긴다.

## 실행 차단

새 packet도 사용자 전수 재검수와 immutable reviewed export 전에는 OFF/ON 점수 실행,
runtime/canonical 승격을 허용하지 않는다.
