# DNF RAG v3.2 development canonical promotion

## 결정

2026-07-21 사용자 명시 승인에 따라 표 row-level atomic facts, global temporal overlay,
duplicate-family overlay를 연결한 v3.2 additive view를 v3 기본 개발 runtime과 canonical
retrieval view로 승격한다.

이 승격은 production-ready, final benchmark 통과 또는 기존 false-full 해결을 의미하지
않는다. 새 sealed canary는 실행하지 않았으며, 기존에 검수된 95문항의 OFF/ON A/B와
artifact 무결성을 근거로 사용자가 해당 gate를 명시적으로 유예했다.

## 승격 범위

- 기본 runtime에서 v3.2 additive 기능을 ON으로 유지한다.
- 표 행은 subject-attribute-value-unit atomic fact로 검색·표시한다.
- current 질문은 global temporal overlay의 명시적 deny revision을 사전 제외한다.
- duplicate-family는 문서를 합치지 않고 provenance metadata만 노출한다.
- 원본 dirty DocumentV3/ChunkV3와 기존 개발·실패 artifact는 삭제하거나 덮어쓰지 않는다.
- `--disable-v3-2-candidates`는 승격 전 baseline 재현을 위한 진단 스위치로 보존한다.

## 승격 근거

- 기존 문항 95개 response mode 변경 0
- 답변 가능 문항 grounded `73/82 → 73/82`
- false-full `9/82 → 9/82`, 새 false-full 0
- evidence-group coverage `96/109 → 96/109`
- 기존 인용 제거 0, 추가 인용 117
- 선택된 atomic fact 165개에서 value가 exact row에 없는 경우 0
- exact row offset mismatch 0
- parent candidate order perturbation 0
- temporal leak 0, gold content loss 0, replacement character 0

## 알려진 제한

- 기존 false-full 9/82는 그대로 남아 있다.
- exact citation은 원문 일치만 보장하며 requirement에 대한 의미적 정답을 보장하지 않는다.
- 새 sealed canary가 없으므로 처음 보는 질문에 대한 독립 일반화 성능은 미측정이다.
- 따라서 이 승격은 개발 기본값 승격이며 외부 production 배포 승격이 아니다.

## 계보

content-addressed promotion manifest가 승격된 모든 입력 SHA, A/B 근거, 사용자 승인에 따른
sealed-canary 유예, 잔여 위험을 고정한다. 기존 dirty canonical은 v3.2 view의 immutable
base로 계속 보존한다.

