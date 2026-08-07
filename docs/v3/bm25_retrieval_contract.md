# DNF RAG v3 BM25 lexical retrieval 계약

## 범위와 판정

전체 ChunkV3 3,599개를 보존하는 결정론적 BM25 index를 만들고, 기본 현재 검색과 과거·preview·OCR 통제 검색의 필터 경계를 검증했다.

- index schema: `dnf_bm25_index_v3.1`
- manifest schema: `dnf_bm25_manifest_v3.1`
- tokenizer: `dnf_lexical_nfkc_word_date_v1`
- BM25 parameters: `k1=1.2`, `b=0.75`
- fixed `built_at`: `2026-07-18T01:35:07+09:00`
- lexical baseline 구현 판정: **GO**
- BGE-M3 tokenizer capacity 판정: **GO**

이 GO는 index·검색·필터 배관이 재현 가능하고 안전하다는 뜻이다. 자연어 질문에 대한 검색 품질을 입증한 평가는 아니다. Dense index, Router, decomposition, generator, verifier, 학습은 실행하지 않았다.

## Index 계약

`retrieval_text`를 NFKC 정규화하고 소문자로 변환한 뒤 숫자, 영문, 한글 음절, underscore의 연속 문자열을 token으로 사용한다. 한국어 날짜, slash 날짜, ISO 날짜에서는 `M/D`, `MM-DD`, `M월`, `D일` 변형도 추가한다.

Index는 모든 청크를 보존한다.

- indexed chunks: 3,599
- vocabulary terms: 29,980
- average lexical document length: 176.56098916365656
- default searchable chunks: 2,527

각 entry는 `chunk_id`, 부모 문서, 공식 URL, title, source, status, exposure, review, validity metadata와 lexical 길이를 가진다. postings는 term별 `(ordinal, term_frequency)` 목록이며 entry와 postings 모두 결정론적으로 정렬된다.

## 기본 검색 안전 정책

기본 검색은 다음 조건을 모두 만족하는 entry만 허용한다.

- `default_exposure=true`
- `status in {current, upcoming}`
- `review_required=false`
- `as_of`가 지정되면 `valid_from <= as_of <= valid_to`; 한쪽 경계가 없으면 존재하는 경계만 적용

따라서 expired, superseded, unknown preview, visual OCR은 index에 남아 있지만 기본 검색에서는 제외된다.

과거·preview 검색은 `default_exposure_only=false`와 구체적인 `allowed_statuses`를 동시에 지정해야 한다. CLI에서는 `--include-non-default`만 단독으로 사용할 수 없고 반드시 `--statuses`를 함께 지정한다. OCR까지 검색하려면 추가로 `--include-review-required`가 필요하다.

```powershell
python src/v3/retrieve_bm25.py "정기점검 업데이트" --top-k 5
python src/v3/retrieve_bm25.py "과거 운영정책" --include-non-default --statuses superseded --no-time-filter
```

두 번째 명령은 역사적 조사용이며 현재 사실 답변의 기본 route로 사용하면 안 된다.

## Smoke 결과

결정론적으로 선택한 희소 title lookup과 통제 검색 결과는 다음과 같다.

- 8개 source 기본 title lookup hit@5: 8/8
- expired, superseded, unknown, OCR 통제 hit@5: 4/4
- default filter policy violation: 0
- non-default target의 기본 검색 누출: 0

Title lookup은 해당 title이 `retrieval_text`에 들어가므로 배관 smoke로만 사용한다. 질문 기반 retrieval hit rate나 exact evidence 성능으로 보고하지 않는다. 기존 frozen blind는 접근하지 않았다.

## BGE-M3 tokenizer 길이 측정

로컬 `BAAI/bge-m3`의 `XLMRobertaTokenizer`로 3,599개 `retrieval_text`를 truncation 없이 측정했다.

| metric | tokens |
|---|---:|
| min | 44 |
| p50 | 252 |
| p90 | 879 |
| p95 | 953 |
| p99 | 1,068 |
| max | 1,187 |

| threshold | over threshold | ratio |
|---:|---:|---:|
| 512 | 1,182 | 32.84% |
| 1,024 | 80 | 2.22% |
| 2,048 | 0 | 0% |
| 8,192 | 0 | 0% |

BGE-M3 tokenizer의 model max length는 8,192다. 현재 snapshot은 2,048에서도 잘리지 않지만 512 또는 1,024를 사용하면 corpus 일부가 잘린다. 다음 dense index 파일럿은 `max_length=2048` 이상을 명시하고 실제 embedding 입력에서도 truncation 0을 재검증해야 한다.

## Canonical artifacts

- BM25 index: `data/v3/indexes/bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json`
- manifest: `data/v3/indexes/bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json`
- smoke: `data/v3/retrieval/bm25_smoke_9a6ea43369174ef761f95e7a371bf9fdcf8e0c5824732e28bea06e4b2fc487c0.jsonl`
- report: `reports/v3/bm25_baseline_905fed042802020d2b0aeefc50136df166cac70fc4d4f71706f156c9741a3acc.json` 및 `.md`

JSON/JSONL 파일명의 64자리 suffix는 해당 파일 bytes의 SHA-256이다. 동일 입력과 고정 `built_at`, 동일 dense measurement payload로 재실행하면 index, manifest, smoke, report hash가 모두 재현된다.

## 다음 단계

다음 사이클은 BGE-M3 dense index **파일럿** 하나로 제한한다. `max_length=2048` 이상, default/status/time/OCR filter parity, embedding 입력 truncation 0, 소규모 lexical-vs-dense 진단을 먼저 검증한다. Router나 hybrid 승격은 별도 retrieval dev gate가 생기기 전에는 시작하지 않는다.
