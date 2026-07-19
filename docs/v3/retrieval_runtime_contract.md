# DNF RAG v3 검색 런타임 계약

## 승격된 개발용 검색기

`src/v3/retrieve_v3.py`는 v3 코퍼스 전용 검색 진입점이다. v2 검색 코드와 인덱스는 변경하지 않는다.

- dense model: `BAAI/bge-m3`
- 후보 깊이: 각 검색기 top-20
- 결합: 질의별 min-max 정규화 후 dense 0.75 + BM25 0.25
- 점수 재현성: 결합 전에 개별 검색 점수를 소수점 8자리로 고정
- 반환 한도: top-1부터 top-20
- 기본 정책: `current`와 `upcoming`, `default_exposure=true`, `review_required=false`, 조회일 유효 범위

과거 정책, 종료 이벤트·상품, 퍼스트 서버 자료는 명시적으로 비기본 상태와 노출 정책을 지정한 호출에서만 검색한다. CLI에서 `--include-non-default`를 쓰려면 `--statuses`도 함께 지정해야 한다.

## 구조화 필드 질의 보정

가격·거래·판매·종료 신호가 있는 질의에만 parent-lead 보정을 적용한다. 기본 하이브리드 상위 8개는 유지하고, BM25 상위 결과에서 서로 다른 부모 문서의 lead chunk를 최대 2개 골라 9~10위에 배치한다.

이 규칙은 gold chunk ID, 정답 document ID, source ID를 사용하지 않는다. 비구조화 질의의 순위는 변경하지 않는다.

## 실행

```powershell
python src/v3/retrieve_v3.py "7월 스페셜 클론 레어 아바타 풀세트 상자의 상점판매가와 거래 타입은?" --top-k 10 --device cuda
```

과거 운영정책처럼 비기본 자료가 필요한 경우의 예시는 다음과 같다.

```powershell
python src/v3/retrieve_v3.py "2022년 3월 17일 운영정책" --top-k 10 --include-non-default --statuses superseded --as-of 2022-03-17
```

## 재현성 게이트

고정된 dev 63문항과 고정 query embedding을 실제 런타임에 재생한 결과, 승격 실험 결과와 top-10 및 top-20 순위가 각각 63/63 완전 일치했다. 구조화 필드 질의 7개도 모두 같은 경로로 판별됐다.

- 런타임 진입점: GO
- 개발용 검색 후보: GO
- 최종 benchmark: NO-GO

최종 benchmark는 실행하지 않았다. 남은 1개 공지 문항의 의미가 여러 공식 문서와 겹쳐 사람 검토가 필요하기 때문이다. 해당 검토가 끝나기 전에는 dev 세트를 다시 freeze하지 않는다.

## 고정 산출물

- replay: `data/v3/retrieval/retrieval_runtime_replay_bff9fe0bc935b960840fb186ce91ae3df43d6d5c2f7df7fd73247ebea9e4a37e.jsonl`
- manifest: `data/v3/retrieval/retrieval_runtime_manifest_6605e9885a6c45d59d9852edc09ef0f93fcff427d8d29747e3d85ef8b7c94f65.json`
- report: `reports/v3/retrieval_runtime_b646709174b72d36ed2ef70cd0228e623054bc9cab38e9fdace143af817c3f8f.json`
