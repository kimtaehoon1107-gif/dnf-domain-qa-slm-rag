# DNF RAG v3 normalized DocumentV3 계약

## 범위

이 사이클은 frozen discovery registry, full detail ledger, hardened extraction preview, visual evidence, redirect correction overlay를 결합해 revision-aware DocumentV3와 별도 content companion을 생성한다. 기존 188개 v3.0 baseline artifact는 수정하거나 덮어쓰지 않는다.

- builder version: `dnf_normalized_corpus_builder_v3.1`
- document schema: `dnf_document_v3.1`
- content schema: `dnf_document_content_v3.1`
- manifest schema: `dnf_normalized_corpus_manifest_v3.1`
- fixed `built_at`: `2026-07-17T23:50:00+09:00`

ChunkV3, 구조화 store, BM25, dense index, Router, 학습은 이 사이클에서 실행하지 않았다.

## Artifact 분리

DocumentV3 envelope와 normalized 본문은 분리한다.

```text
DocumentV3 envelope
  document_id, source/revision/status/default exposure, hashes, raw provenance

DocumentContentV3
  document_id, hardened DOM text, extraction metadata/warnings,
  별도 visual OCR evidence
```

본문을 envelope에 중복 저장하지 않는다. 두 artifact는 `document_id` 일대일 관계이며, `normalized_text_hash == content.text_hash`를 필수로 검증한다.

OCR text는 DOM text에 이어 붙이지 않는다. `visual_evidence.unverified_ocr=true`인 별도 보조 근거로만 저장하고 `visual_ocr_unverified_supplement` warning을 유지한다. OCR은 단독 authoritative fact가 아니다.

## Document ID와 hash

새 detail document의 `content_hash`는 다음 payload의 canonical JSON SHA-256이다.

```text
content_hash_version
title
source_kind
category_path
published_at
valid_from
valid_to
hardened DOM text
visual_text_hash 또는 null
```

- `document_id = SHA-256(canonical_url + newline + content_hash)`에 `document_sha256_` prefix를 붙인다.
- `revision_id`는 같은 identity hash에 `revision_sha256_` prefix를 붙인다.
- `raw_content_hash`는 immutable raw detail snapshot bytes의 SHA-256이다.
- `source_snapshot_id`는 `raw_content_hash` 기반이다.
- `normalized_text_hash`와 `visual_text_hash`는 각 text UTF-8 bytes의 SHA-256이며 서로 섞지 않는다.

material revision으로 보존한 기존 `guide?no=1535` baseline은 기존 v3.0 `document_id`, `revision_id`, `content_hash`를 그대로 유지한다.

## Category와 source kind

- `source_kind`는 frozen discovery registry 값을 사용한다.
- `category_path` 첫 요소는 `source_kind`다.
- registry category가 비어 있지 않고 `unknown`이 아니며 source kind와 다르면 두 번째 요소로 둔다.
- 공지의 세부 `source_kind`는 listing classifier provenance이므로 후속 구조화 store에서 본문 기반 재분류를 할 수 있지만, 현재 artifact에서 조용히 추정 변경하지 않는다.

## 날짜·상태·기본 노출

- `published_at`, `valid_from`, `valid_to`는 hardened preview 값을 우선하고 없으면 registry 값을 사용한다.
- `status`는 frozen registry 상태를 보존하되 lineage 내 최신 revision이 아닌 행은 `superseded`로 강제한다.
- `default_exposure=true`는 `current` 또는 `upcoming`만 가능하다.
- `preview_patch`, `roadmap_statement`는 status와 무관하게 기본 노출할 수 없다.
- correction overlay의 3개 redirect row는 DocumentV3로 생성하지 않고 manifest/report의 exclusion으로 보존한다.

## Revision lineage

일반 문서는 canonical URL별 lineage를 사용한다.

운영정책은 revision query가 canonical URL에 보존되므로 URL만으로 묶지 않는다. `source_id=dnf_account_policy`인 row는 공통 policy listing URL을 lineage key로 사용하고 시행일 순서로 51개 revision을 연결한다. oldest revision만 `supersedes_document_id=null`이고, 이후 revision은 바로 이전 document를 가리킨다. 최신 revision 한 개만 current/default exposure다.

게임가이드 `guide?no=1535`는 parser hardening에서 `official_revision_after_baseline`으로 검증됐다. 기존 2026-07-05 baseline revision을 `superseded/default_exposure=false`로 보존하고, 2026-07-17 detail revision이 이를 supersede한다. 나머지 124개 guide는 material change가 확인되지 않아 parser 표현 차이를 별도 source revision으로 만들지 않는다.

## 실제 결과

| source | DocumentV3 | default exposure | 상태 |
|---|---:|---:|---|
| `dnf_account_policy` | 51 | 1 | current 1, superseded 50 |
| `dnf_event` | 24 | 24 | current 24 |
| `dnf_faq` | 279 | 279 | current 279 |
| `dnf_game_guide` | 126 | 125 | current 125, superseded 1 |
| `dnf_monthly_item` | 14 | 1 | current 1, expired 13 |
| `dnf_notice` | 396 | 396 | current 396 |
| `dnf_seria_shop` | 72 | 30 | current 30, expired 42 |
| `dnf_update` | 18 | 15 | current 15, unknown preview 3 |
| **합계** | **980** | **871** | current 871, expired 55, superseded 51, unknown 3 |

- detail normalization candidate: 979
- 보존한 material baseline revision: 1
- redirect exclusion: 3
- content companion: 980
- visual evidence companion 보유: 18
- 빈 title/text: 0
- invalid status: 0
- default exposure policy violation: 0
- raw/text/content hash mismatch: 0

## Canonical artifacts

- DocumentV3: `data/v3/normalized/documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl`
- content companion: `data/v3/normalized/document_contents_dnf_official_detail_v3.1_5fe50f7fcbd7adbf415bbb1f1ebb8ef3684f7b2c61ac2b2ace9d0e4365b3080e.jsonl`
- manifest: `data/v3/normalized/normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json`
- report: `reports/v3/document_v3_promotion_bd6110d4201e8669ce096069bbdec6a4f0373ab2661bb9ae385dadb27b9093d4.json` 및 `.md`

각 JSON/JSONL 파일명의 64자리 suffix는 해당 파일 bytes의 SHA-256이다. 같은 frozen 입력과 `built_at`으로 재실행하면 같은 경로와 hash를 재사용한다. 중간 판정 규칙 보정 전에 생성된 report는 immutable 실행 이력이며 위 report만 canonical이다.

## 판정과 다음 단계

- normalized DocumentV3 promotion: **GO**
- ChunkV3 설계·파일럿 진입: **GO**

다음 사이클은 980개 전체를 즉시 단일 규칙으로 chunk하지 않는다. 먼저 source별 구조 보존 계약을 만들고, 표·heading·offset·visual evidence 연결을 검증하는 결정론적 ChunkV3 파일럿을 수행해야 한다. current/default exposure filter와 superseded/expired/preview exclusion은 chunk와 retrieval metadata에도 그대로 전파한다.
