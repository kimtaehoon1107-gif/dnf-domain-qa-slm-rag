# DNF RAG v3 strong-judge claim ceiling diagnostic

## 목적과 지위

이 진단은 requirement-slot 접근이 네 차례 실패한 뒤 세만틱 runtime을 만들기 전에
post-retrieval claim completeness의 천장을 측정한다. 강한 judge는 진단 도구일 뿐이며
runtime, reranker, canonical evidence selector 또는 Generator로 승격하지 않는다. 기존
32개 authored canary는 `adaptive_validation_diagnostic_only` 상태를 유지하고 새 질문,
gold, canary를 만들지 않는다.

모델은 `--model` 또는 `MODEL` 환경변수로 고정한다. 기본 원격 후보는
`gpt-5.6-sol`이지만, 로컬 ceiling 실행은 `OPENAI_BASE_URL=http://localhost:11434/v1`,
`OPENAI_API_KEY=ollama`, `MODEL=qwen2.5:7b-instruct`를 사용한다. 로컬 Ollama에는
OpenAI 전용 reasoning parameter를 보내지 않고 `temperature=0`으로 고정한다. 실제
base URL, 모델 태그와 digest, Ollama 버전, API가 반환한 model ID, OpenAI SDK 버전,
실행 일시를 결과와 run manifest에 기록한다.

OpenAI 호환 endpoint에서는 요청별 context 크기를 지정할 수 없으므로 부모 문서 전체가
4096-token 기본값에서 잘리지 않게 원본 가중치를 보존한 진단 전용 파생 태그
`dnf-claim-ceiling-qwen2.5-7b:ctx32768`을 사용한다. 이 태그는
`Modelfile.claim_ceiling_qwen2_5_7b`의 `num_ctx 32768`, `temperature 0` 외에는
원본 모델을 변경하지 않는다.

## 고정 모집단

강등된 32-set에서 required evidence group이 둘 이상이고 한 parent document가 모든
group을 덮는 15개 질문만 사용한다. 기존 canonical claim completeness는 3/15이고
실패는 12개다. 63 dev의 복합질문 4개는 모두 cross-parent이므로 이번 same-parent
조건 B를 정의할 수 없어 포함하지 않는다.

각 질문은 같은 judge에 독립 요청 두 번으로 평가한다.

- 조건 A: 최초 sealed canary 실행의 실제 `retrieval_chunk_ids` top-10만 제공한다.
- 조건 B: 모든 required group을 덮는 공통 parent의 canonical ChunkV3 전체를
  `chunk_index` 순서로 제공한다.

조건 A와 B는 서로 다른 요청이다. B context가 A 판정에 보이지 않도록 하며 gold
group, acceptable chunk ID, evidence span은 어느 prompt에도 전달하지 않는다.

## Judge 출력 계약

judge는 질문 순서대로 독립 요구 항목을 열거한다. 각 항목은 다음 필드를 가진다.

- `entity`
- `attribute`
- `value_type`
- `qualifiers`
- `verdict`: `fully_supported`, `partially_supported`, `unsupported`
- `evidence_spans`: condition context의 chunk ID와 그대로 복사한 연속 원문

개체 귀속과 수치, 시점, 조건, 예외를 보존해야 한다. `fully_supported`는 모든 요소가
근거로 지지될 때만 허용한다. 최종 답변 prose는 생성하지 않는다. span은 실제 chunk의
연속 부분 문자열인지 코드로 검증한다.

계획된 judge는 OpenAI `gpt-5.6-sol`, reasoning effort `high`다. 실제 실행 manifest에는
요청 model ID, API가 반환한 model ID, OpenAI SDK version, 실행 날짜, token usage,
호출별 비용과 latency를 기록한다. API key와 hidden reasoning은 저장하지 않는다.

## Gold 채점

gold는 judge 호출이 끝난 뒤에만 사용한다. `fully_supported` 항목의 exact span이 기존
acceptable chunk에 속하고 gold evidence span token recall이 0.50 이상이면 해당
evidence group을 회복한 것으로 본다.

- claim completeness: 모든 required group이 회복되고 false-support가 0인 질문 수
- support decision accuracy: 각 condition에서 group의 근거가 실제 제공되었는지와
  회복 판정이 일치한 비율
- false-support: `fully_supported`이지만 어느 gold group에도 정렬되지 않는 항목

이 정렬은 evaluation-only다. gold ID는 runtime 함수나 judge prompt에 전달하지 않는다.
judge는 질문에 나타난 순서대로 requirement를 열거하고, 채점기는 같은 순서의 기존
evidence group에만 span을 대응한다. 따라서 다른 gold group의 span을 우연히 인용하거나
질문에 없던 항목을 추가해도 정답으로 인정하지 않는다. 기존 gold에 개체·속성 구조 라벨이
없으므로 동일 순번에서 잘못된 속성이 올바른 span을 인용하는 오류까지 자동 검출할 수는 없다.
이 한계 때문에 false-support가 1건이라도 나오면 자동 승격하지 않고 독립 사람 확인을 요구한다.

## 사전 고정 판정

- 조건 A가 baseline 실패 12개 중 10개 이상 회복하고 false-support가 0이면
  `PATH_1_SEMANTIC_BUILD`다.
- 조건 A는 10개 미만, 조건 B는 10개 이상 회복하면 `RETRIEVAL_REDIRECT`다.
- A와 B 모두 10개 미만이면 `PATH_2_STOP_SEMANTIC_BUILD`다.
- false-support 1~2개면 자동 판정을 보류하고 독립 사람 확인을 요구한다.
- false-support 3개 이상이면 judge를 신뢰하지 않고 재선정한다.
- API 또는 structured/span 검증 실패가 하나라도 있으면 결과는 inconclusive다.

## 범위 제한

- 자유형 답변 생성, 학습, 새 키워드, 새 canary를 만들지 않는다.
- router, decomposition, retrieval, canonical claim output을 변경하지 않는다.
- 기존 질문·gold·실패 artifact를 수정하거나 삭제하지 않는다.
- frozen blind, v2, `AGENTS.md`, `docs/dnf_rag_v3_agent_handoff.md`, `src/outputs`에
  접근하거나 수정하지 않는다.
