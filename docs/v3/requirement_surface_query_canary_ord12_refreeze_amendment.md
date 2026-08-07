# Requirement surface-query canary ord=12 refreeze amendment

## 상태

직전 content-addressed packet의 사용자 전수 검수 결과는 31개 승인, ord=12 한 개 기각이다.
직전 packet·manifest·report와 검수 기록은 삭제하거나 덮어쓰지 않는다.

## 허용된 변경

ord=12의 세 번째 요구인 `열대야의 추억 오라 확정 변경권 삭제 시각`만 교정한다.

- 근거 청크: `chunk_sha256_8bacceaaf7f9215dd9837f65d63dc4491d3b53429fe963e5c66c1bc1322473c2`
- 근거 범위: 해당 청크 `display_text[65:235]`
- 근거 의미: 아이템명부터 삭제 시각까지 포함한 170자 연속 exact slice
- 부모 문서: 기존과 동일

직전의 `Special Gift` 중복 매치는 다른 이벤트의 일반 삭제 보일러플레이트이므로
`EQUIVALENT_OFFICIAL`이 아니다. acceptable sibling으로 추가하지 않는다.

그 외 31개 행의 `question_text`, `requirements`, `evidence_groups`, `gold_answer`,
`gold_chunk_ids`, `gold_document_ids`는 직전 packet과 동일해야 한다.

## 승인 기록과 실행 차단

Codex는 승인 결정을 미리 채우지 않는다. 사용자가 검수 앱에서 각 행을 직접 판정해야 한다.
32개 전부 승인되고 기각과 미검수가 모두 0일 때만 immutable 검수 기록을 export할 수 있다.
이 export도 점수 실행 권한을 부여하지 않는다. 별도 사용자 승인 전까지 sealed scoring,
final benchmark, independent holdout, training 및 runtime/canonical 승격은 모두 차단한다.
