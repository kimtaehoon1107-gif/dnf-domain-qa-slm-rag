# DNF RAG v3 ChunkV3 전체 코퍼스 계약

## 범위와 입력

승격된 DocumentV3 980개 전체에 파일럿에서 검증한 오프셋 보존형 청크 규칙을 적용하고 corpus-wide 무결성 감사를 수행했다.

- chunker version: `dnf_offset_chunk_v3.1`
- chunk schema: `dnf_chunk_v3.1`
- manifest schema: `dnf_chunk_corpus_manifest_v3.1`
- audit schema: `dnf_chunk_corpus_audit_v3.1`
- fixed `built_at`: `2026-07-18T01:10:47+09:00`
- indexing 진입 판정: **GO**

Canonical 입력은 다음 네 개이며 builder 종료 시에도 SHA-256 불변을 다시 검사한다.

- DocumentV3 980행: `d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d`
- DocumentContentV3 980행: `5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e`
- normalized corpus manifest: `3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf`
- approved pilot manifest: `ba5e1d5a9b8a237df9a99e5fb698bbb8e0a4b6dc1668b3cabece9e971e0154e6`

## 전체 적용 전 보정

파일럿 규칙을 980개에 메모리상 사전 적용했을 때 표본 밖에서 두 가지가 확인됐다.

- 개인정보처리방침 비교표의 단일 행 1개가 2,335자로 공지 상한 1,200자를 초과했다.
- 이미지 중심 이벤트, 게임가이드, 업데이트에서 80자 미만 고립 span 5개가 남았다.

초장문 표 행은 문장/공백 경계의 정확한 원문 offset으로 나누고 각 조각을 table unit으로 유지한다. 인접 span과 합치면 상한을 넘는 짧은 section은 인접 원문 안으로만 확장해 bounded overlap을 만든다. 문자를 새로 삽입하거나 표 내용을 평탄화하지 않는다.

이 보정은 기존 63개 pilot 표본의 bytes와 hash를 바꾸지 않았다. 전체 재측정에서는 oversized와 orphan이 모두 0이다.

## 전체 결과

| source | documents | DOM chunks | visual OCR chunks |
|---|---:|---:|---:|
| `dnf_account_policy` | 51 | 607 | 0 |
| `dnf_event` | 24 | 150 | 8 |
| `dnf_faq` | 279 | 282 | 13 |
| `dnf_game_guide` | 126 | 974 | 1 |
| `dnf_monthly_item` | 14 | 49 | 0 |
| `dnf_notice` | 396 | 786 | 0 |
| `dnf_seria_shop` | 72 | 476 | 0 |
| `dnf_update` | 18 | 253 | 0 |
| **합계** | **980** | **3,577** | **22** |

- 전체 청크: 3,599
- visual evidence 문서: 18
- 기본 노출 문서: 871
- 기본 노출 청크: 2,527
- table 또는 mixed DOM 청크: 1,477
- heading path 보유 DOM 청크: 3,287
- 상태: current 871, expired 55, superseded 51, unknown 3
- DOM 문자 길이: min 80, p50 419, p95 1,777, max 1,800
- 결정론적 lexical token 추정치: min 22, p50 135, p95 543, max 706

`unicode_word_punct_v1` token count는 모델 tokenizer 길이가 아니다. 이후 dense index를 만들 때는 선택한 embedding model tokenizer로 truncation을 별도 측정해야 한다.

## Corpus-wide 감사 게이트

다음 항목은 전부 0이며 문서 수와 출처 집합 boolean 게이트도 통과했다.

- document/content ID 집합 불일치와 중복 ID
- DOM 청크가 없는 부모 문서와 visual evidence가 누락된 부모 문서
- 유효하지 않은 offset/source와 비공백 coverage gap
- `source_text[start_offset:end_offset]`와 `display_text` 불일치
- `chunk_id`, chunk index/count sequence, chunker/schema version 불일치
- 빈 display/retrieval text와 retrieval text 재현 불일치
- token count, normalized text hash, parent content hash 불일치
- 부모 source/status/date/default exposure metadata 불일치
- expired/superseded/preview의 기본 노출 정책 위반
- visual OCR의 검토·노출 정책 위반
- 출처별 max/overlap 설정 위반
- 길이 상한 초과와 다중 청크 문서의 80자 미만 고립 청크

visual OCR 22개는 계속 `review_required=true`, `evidence_quality=unverified_ocr`, `default_exposure=false`다.

## Canonical artifacts

- chunks: `data/v3/chunks/chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl`
- manifest: `data/v3/chunks/chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json`
- audit report: `reports/v3/chunk_corpus_audit_6526c24d365bff8433079ecd551afda35f9e56bc561cc04da56198fbd1a6a7c9.json` 및 `.md`

JSON/JSONL 파일명의 64자리 suffix는 해당 파일 bytes의 SHA-256이다. 동일 입력과 고정 `built_at`으로 재실행하면 세 hash와 경로가 그대로 재현된다.

## 다음 단계

ChunkV3 전체 코퍼스가 corpus-wide 감사에 통과했으므로 lexical retrieval 구현 진입은 **GO**다. 다음 사이클은 먼저 BM25 index manifest와 default exposure/time/status filter 계약을 만들고, 작은 retrieval smoke 및 truncation 측정을 수행해야 한다. dense index, Router, decomposition, generator, verifier, 학습은 한 사이클에 함께 확장하지 않는다.
