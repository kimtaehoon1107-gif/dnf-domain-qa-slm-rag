# DNF RAG v3 구조화 필드·부모 lead 검색 신호 계약

## 문제와 범위

고정 hybrid grid의 최선 설정 `dense_75_bm25_25`는 평균 성능을 개선했지만 세리아 상점의 최저 출처 성능이 개선되지 않아 승격되지 않았다. 실패를 확인한 결과 상품·기간 문서 자체는 상위에 적중했으나, 긴 표나 여러 섹션 때문에 정답이 있는 첫 청크가 top-10 밖으로 밀렸다.

이번 사이클은 이 부모 문서 적중/근거 청크 누락만 다룬다. BM25·dense 인덱스와 임베딩은 다시 만들지 않으며 Router, 일반 query decomposition, generator, verifier, 학습, frozen blind 평가는 수행하지 않는다.

## 일반 규칙

질문에 다음 구조화 필드 신호 중 하나가 있을 때만 guard를 적용한다.

- `가격`
- `거래`
- `판매`
- `종료`

규칙은 다음과 같다.

1. frozen `dense_75_bm25_25` 순위를 기본으로 사용한다.
2. BM25 결과에서 서로 다른 상위 2개 부모 문서를 선택한다.
3. 각 부모의 일반 텍스트 `chunk_index=1`을 lead chunk로 선택한다.
4. lead가 top-10에 없으면 기존 top-8을 유지한 채 9~10위에 보존한다.
5. gold chunk ID, gold document ID, `source_ids`는 순위 결정에 사용하지 않는다.

한 부모에 DOM text와 visual OCR lead가 모두 있으면 `review_required=false`, 비-OCR, `chunk_id` 순으로 하나를 결정한다. query policy가 허용하지 않는 lead는 넣지 않는다.

## 비교 기준

새 후보는 dense 단독뿐 아니라 이전 최선 hybrid와도 비교한다. 다음을 모두 만족해야 개발 검색 후보로 승격한다.

- hit@10, all-groups@10, group recall@10 개선
- MRR 비회귀
- 8개 출처별 all-groups@10 회귀 0
- 최저 출처 all-groups@10 개선
- dense 단독보다 hit@10과 all-groups@10 우세

## 결과

| system | MRR | hit@10 | all groups@10 | group recall@10 |
|---|---:|---:|---:|---:|
| dense | 0.6446 | 0.9455 | 0.9273 | 0.9322 |
| fixed hybrid | 0.7085 | 0.9636 | 0.9455 | 0.9492 |
| signal candidate | 0.7093 | 0.9818 | 0.9818 | 0.9831 |

구조화 필드 질문 7개에서 lead chunk 7개가 top-10에 보존됐다. 세리아 상점 all-groups@10은 0.6667에서 1.0으로 개선됐으며 다른 7개 출처의 회귀는 0이다. 최저 출처 값도 0.6667에서 0.8571로 개선됐다. 모든 개발 승격 gate가 통과했으므로 후보는 **v3 retrieval development candidate GO**다.

이는 최종 benchmark 승격이 아니다. `비인가 프로그램 사용 주의사항은 뭐야?` 문항은 현재 gold 이외의 운영정책·FAQ도 답을 제공할 가능성이 있어 `human_review_required`로 남긴다. 이 검수와 별도 benchmark freeze 전까지 최종 판정은 **NO-GO**다.

## Frozen artifacts

- results: `data/v3/retrieval/retrieval_signal_results_c8f5c902f237ef70b4add45ee63815bd1cdafeb84741c86c1bd634b1df02127e.jsonl`
- manifest: `data/v3/retrieval/retrieval_signal_manifest_65e0a1e210aae40c2a610e69a1cf79f90ef79e8b39bd9e971c2e9029fc9358ca.json`
- report: `reports/v3/retrieval_signal_e476a6f9f0c310bb952aadf1d128f16a711fcab4019512493f575c174e20555d.json`
- readable report: `reports/v3/retrieval_signal_a4bace8ed2c24eeb6fb57335a0d4e2e0d7816722ef7b52035c26a21ea2ccdbf8.md`

파일명의 마지막 64자리는 해당 파일 bytes의 SHA-256이다. 같은 frozen 입력으로 재실행하면 동일 artifact hash가 나와야 한다.
