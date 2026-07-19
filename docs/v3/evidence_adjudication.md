# DNF RAG v3 evidence adjudication 계약

이 단계는 adaptive dev에서 claim-aware reranker가 선택한 공식 청크와 기존
`acceptable_chunk_ids`가 어긋난 항목만 사람에게 다시 보여 준다. 원래 retrieval
dev artifact와 reranker artifact는 수정하거나 덮어쓰지 않는다.

## 판정

- `accept_alternative`: 후보 청크도 질문의 핵심 claim을 완전하고 직접적으로
  지지한다. 기존 expected와 후보를 모두 평가 가능한 근거로 유지한다.
- `reject_alternative`: 후보가 핵심 조건을 빠뜨리거나 다른 질문에 답하므로 기존
  expected를 유지한다.
- `confirm_search_failure`: 기존 acceptable 청크가 routed candidates에 없으므로
  gold를 넓히지 않고 검색 실패를 유지한다.

대안 승인에는 후보 청크에 정확히 존재하는 결정적 문구와 10자 이상의 사유가
필요하다. reviewer는 실제 사람 ID를 사용한다. 어떤 판정도 기존 gold를
교체하지 않는다.

저장된 `review_rationale` 또는 `decisive_excerpt`에 물음표 치환이 5개 이상
나타나면 명백한 인코딩 손상으로 간주한다. 손상된 행은 완료 수에 포함하지 않고
저장 및 immutable export를 거부한다. 기존 판정과 정상 발췌문은 유지한 채 손상된
검수 문장만 사람이 다시 입력한다.

## 격리

검수 packet은 `data/v3/evaluation`에 content-addressed artifact로 저장한다. 작업
중 draft만 `outputs/v3/annotation`에서 변경할 수 있다. 완료된 review, evaluation
overlay와 manifest는 다시 content-addressed artifact로 freeze한다.

overlay는 평가 후 strict ID 대조에만 사용한다. reranker runtime에는 질문, 후보
청크와 기존 BGE 점수만 전달하며 gold answer, expected span, acceptable ID와 사람
판정을 전달하지 않는다.

이 검수는 adaptive dev annotation 보정이며 학습과 final benchmark에 사용할 수
없다. strict mismatch를 모두 닫더라도 독립 holdout 전에는 production evidence
selector와 final benchmark 판정을 `NO-GO`로 유지한다.
