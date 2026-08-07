# DNF RAG v3 schema-constrained extractive Generator/Verifier 계약

## 범위

Decomposition 이후 hybrid retrieval·Evidence Selector·merge를 통과한 4개 adaptive dev
부모 질문과 8개 child slot을 답변 계획으로 변환한다. 이번 Generator는 자유 생성이나
paraphrase를 하지 않는다. 각 child의 selector top-1 ChunkV3에서 최대 700자의 연속 원문
구절 하나를 결정론적으로 선택한다.

## Answer plan

각 claim에는 다음 결합이 반드시 보존된다.

- parent와 child ordinal, `subquestion_id`;
- `current`, `historical`, `comparison` time scope와 사용자 표시용 기준 시점;
- claim으로 사용한 연속 원문 구절;
- `chunk_id`, parent document ID, source ID/kind;
- lineage와 revision ID, status, validity interval, default exposure.

현재와 과거 claim은 하나의 전역 최신성 순위로 섞지 않고 별도 slot으로 렌더링한다.
Generator는 retrieval dev의 gold chunk ID나 evidence span을 입력으로 받지 않는다.

## 결정론적 Verifier

답변 반환 전 다음을 모두 검사한다.

- 모든 child가 정확히 하나의 claim을 가짐;
- citation chunk가 해당 child의 selected evidence와 merged packet에 포함됨;
- claim이 cited `display_text`의 정확한 연속 부분 문자열임;
- source ID/kind가 child route와 일치함;
- current claim은 current/upcoming이며 default exposure임;
- historical month claim은 문서 validity interval과 해당 월이 겹침;
- 운영정책 claim은 Temporal Policy가 선택한 document/revision과 일치함;
- 같은 lineage의 여러 revision은 명시적 comparison 또는 current/historical 분리일 때만 허용;
- 렌더링된 답변에 claim 원문과 chunk citation이 모두 존재함.

하나라도 실패하면 해당 answer plan은 fail-closed 처리한다.

## Adaptive gate와 한계

post-hoc 감사에서 8개 claim citation이 8개 검수 evidence group을 모두 덮고, 각 claim의
gold evidence-span token recall 최솟값이 0.50 이상이어야 한다. Gold는 이 감사에만
사용한다.

이 단계의 GO는 extractive answer plumbing과 deterministic support verification만 뜻한다.
자연어 Generator, paraphrase 검증, 자연 contradiction NLI, 독립 holdout, final blind는
포함하지 않는다.
