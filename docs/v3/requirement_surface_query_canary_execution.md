# Requirement surface-query canary 실행 계약

## 역할

`evaluate_requirement_surface_query_canary.py`는 사람 검수를 마친 32-slot authored feature
canary를 OFF/ON으로 한 번만 실행하는 전용 채점기다. 기존 93문항 개발 채점기나 저장된
OFF 결과를 재사용하지 않는다. 이 평가는 independent holdout 또는 최종 benchmark가 아니다.

## 동일 실행 보장

각 질문에서 다음 항목은 한 번만 계산해 두 arm이 공유한다.

- Ollama planner 출력
- entity anchor 결과
- 질문 라우팅과 source 범위
- BM25+BGE-M3 후보 검색과 temporal filter
- chunk reranker 결과와 최종 후보 청크

OFF는 anchor된 requirement를 그대로 segment scorer에 넣는다. ON은 같은 requirement와 같은
후보를 사용하되 `entity-coordinated-surface-query-v3.3.1`이 적용될 때만 scoring relation을
surface 표현으로 바꾼다. control에서 기능이 bypass되면 ON 결정 객체는 OFF 객체를 그대로
재사용한다. threshold, K, 검색 범위, 모델, 인덱스는 arm 사이에서 바뀌지 않는다.

## Gold 격리

런타임 runner에 전달되는 필드는 `candidate_id`, `question_text` 두 개뿐이다. authored
requirement, evidence group, acceptable chunk ID, evidence span은 두 arm 실행이 끝난 뒤 채점
함수에서만 읽는다. 사례별 정답 literal이나 target chunk ID는 채점기 소스에 둘 수 없다.

## 실행 차단과 1회 토큰

사람 검수 export 자체는 계속 `sealed_run_count_allowed=0`과
`sealed_scoring_allowed=false`를 유지한다. 따라서 export만으로는 채점할 수 없다.

검수 후 별도 `authorize` 명령이 다음을 content-addressed authorization에 고정한다.

- reviewed packet 및 reviewed manifest SHA-256
- evaluator, surface-query, entity-anchor, 데모 runtime 소스 SHA-256
- canonical chunk/document, assembler, temporal, table index, runtime pointer SHA-256
- reranker model/revision/max length
- Ollama planner tag와 `tag-only` 식별 범위

`run`은 authorization과 현재 파일 해시가 하나라도 다르면 실패한다. 모델 호출 전에
`STARTED_AUTHORIZATION_CONSUMED` 원장을 immutable로 기록하므로 중도 실패도 1회 사용으로
간주한다. 같은 authorization SHA가 시작 또는 완료 원장에 존재하면 재실행을 거부한다.

```powershell
python src/v3/evaluate_requirement_surface_query_canary.py authorize `
  --reviewed <reviewed.jsonl> `
  --reviewed-manifest <reviewed_manifest.json> `
  --approved-by <user-id>

python src/v3/evaluate_requirement_surface_query_canary.py run `
  --reviewed <reviewed.jsonl> `
  --reviewed-manifest <reviewed_manifest.json> `
  --authorization <authorization.json>
```

현재 reviewed export가 없거나 32건 전부 승인되지 않은 상태에서는 두 명령 모두 성공할 수
없다. authorization 생성은 사용자 검수 완료 뒤에만 수행한다.

## 사전 고정 gate

기존 canary 계약의 모든 gate를 기계적으로 계산한다.

- candidate all-required evidence coverage 비회귀
- strict question regression 0
- literal evidence-span regression 0
- strict 또는 literal improvement 1건 이상
- positive 적용 16/16, control bypass 16/16, bypass 출력 변동 0
- false-full 0, exact citation 100%, 신규 surplus citation 0
- requirement citation precision 비회귀
- temporal/revision/preview/expired 누출 0
- source별 positive coverage 1/2 이상, zero-hit source 0

추가 무결성 가드로 runtime requirement 수와 reviewed requirement 수가 모든 행에서 일치해야
한다. 결과가 GO여도 runtime/canonical은 자동 승격하지 않으며 실행 원장에도 이를 false로
고정한다.
