# DNF RAG v3 검색 개발 세트 계약

## 범위와 용도

이 세트는 canonical DocumentV3/ChunkV3를 대상으로 BM25, dense, 이후 hybrid 검색을 같은 근거 기준으로 비교하기 위한 개발용 평가 입력이다. 학습 데이터도 최종 blind benchmark도 아니다.

- schema: `retrieval-dev-v3.1`
- builder: `retrieval-dev-builder-v3.1.0`
- rows: 63
- `training_allowed`: 항상 `false`
- `final_benchmark_eligible`: 항상 `false`
- 기존 frozen blind: 미사용·미접근

이번 사이클은 세트 설계와 freeze까지만 수행한다. BM25/dense 점수, hybrid 가중치, Router, decomposition, generator, verifier, 학습 성능은 측정하지 않는다.

## 입력과 provenance

근거가 있는 기존 비-blind 개발 문항 가운데 evidence span이 현재 ChunkV3에 정확히 다시 매핑되고, 한 부모 문서로 유일하게 귀속되는 문항만 재사용한다. 여기에 기존 개발 세트에 없던 FAQ·운영정책·세리아 상점·이달의 아이템과 multi-evidence 통제 문항을 canonical chunk에서 직접 작성했다.

각 row는 다음 provenance를 보존한다.

- 기존 문항: source role, 원본 파일, 원본 `eval_id`, seed ID
- v3 직접 문항: canonical chunk corpus, seed ID, 검토 상태

기존 fresh paraphrase는 adaptive dev로만 유지한다. human partial은 기존 human-reviewed dev로 표시한다. 직접 작성 문항은 `agent_grounded_review`이며 최종 benchmark 승격 전 별도 사람 검수가 필요하다.

## 근거 계약

`evidence_groups`의 각 항목은 하나의 필수 근거 단위다.

- `evidence_span`: ChunkV3 `display_text`에 공백 정규화 후 그대로 존재해야 한다.
- `acceptable_chunk_ids`: overlap 청킹 때문에 같은 사실을 담는 청크가 여러 개면 모두 허용한다.
- `document_ids`: 한 evidence group은 정확히 한 부모 문서에만 속해야 한다.
- `required_evidence_group_count`: 정답 판정에 필요한 group 수다.

따라서 single-fact 문항은 해당 group의 허용 청크 중 하나를 찾으면 된다. multi-evidence 문항은 모든 필수 group을 찾아야 한다. `answerability=false` 문항은 gold document, chunk, evidence, answer가 모두 비어 있어야 한다.

## 시간·상태 필터 계약

각 문항은 `query_policy`에 다음을 기록한다.

- `default_exposure_only`
- `allowed_statuses`
- `include_review_required`
- `as_of`

현재 사실 문항은 기본 노출 검색을 사용한다. 종료 이벤트·종료 상품·과거 정책은 `default_exposure_only=false`인 historical control로만 허용한다. 퍼스트 서버 표본은 preview control이며 기본 현재 검색에 노출하면 안 된다. current, expired, superseded, unknown 상태가 모두 세트에 존재한다.

## 구성과 gate

| 구분 | 수 |
|---|---:|
| true | 47 |
| partial | 8 |
| false | 8 |
| single fact | 39 |
| multi evidence | 4 |
| historical control | 3 |
| preview control | 1 |

공지, 업데이트, 이벤트, 게임가이드, FAQ, 운영정책, 세리아 상점, 이달의 아이템 8개 `source_id`를 모두 포함한다.

freeze gate는 63행, 질문·ID 중복 0, answerable 근거 누락 0, false gold 오염 0, 8개 출처와 필수 상태·query kind 포함, 학습/final benchmark 플래그 위반 0을 요구한다. 통과하면 retrieval A/B 실행만 **GO**다. hybrid 승격은 실제 비교 전까지 **NOT_RUN**, 최종 benchmark는 사람 검수와 별도 freeze 전까지 **NO-GO**다.

## Frozen artifacts

- seed spec: `data/v3/evaluation/retrieval_dev_seed_spec_a625cc01df6fe746f104e2b868dc7ddcd49fa50ce8350c202f20cda1950e113b.jsonl`
- dev set: `data/v3/evaluation/retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl`
- manifest: `data/v3/evaluation/retrieval_dev_manifest_bb5a858702d8b8c0c267f35309db75221f8e9d5515e30f34b4e6b9dfb17dcec3.json`
- report: `reports/v3/retrieval_dev_set_7dc0075638afbe0803ae0926e479ba1cb0050cedc53b224026a0ced5800025be.json` 및 `reports/v3/retrieval_dev_set_faf4e2aa58417ab769734aeb8983fba6998a2bf698bc23f44a477b69f2176689.md`

파일명의 마지막 64자리 값은 해당 파일 bytes의 SHA-256이다. 같은 입력으로 row를 다시 만들면 동일 dev set hash가 나와야 한다.
