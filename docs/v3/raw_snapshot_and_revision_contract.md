# DNF RAG v3 raw snapshot·revision 계약

## 범위

이 계약은 v2 raw JSONL을 수정하지 않고 v3의 immutable snapshot, corpus manifest, revision-aware `DocumentV3` metadata envelope로 승격하는 규칙만 다룬다. 본문 재파싱과 chunk 생성은 다음 사이클의 별도 변경이다.

`DocumentV3`에는 본문을 중복 저장하지 않는다. 원문은 `raw_source_path`의 immutable snapshot에 남고, `canonical_url`과 `content_hash`로 해당 행을 다시 식별한다.

## artifact 명명

```text
data/v3/raw_snapshots/raw_snapshot_{source_name}_v2_{source_sha256[:12]}.jsonl
data/v3/raw_snapshots/corpus_manifest_{corpus_name}_v3.0_{manifest_id_hash[:12]}.json
data/v3/normalized/documents_{corpus_name}_v3.0_{manifest_id_hash[:12]}.jsonl
```

- `latest` 같은 가변 별칭은 만들지 않는다.
- snapshot은 원본 파일의 바이트를 그대로 복사한다.
- 같은 경로에 같은 바이트가 이미 있으면 재사용하고, 다른 바이트가 있으면 덮어쓰지 않고 실패한다.
- manifest에는 실행 시각을 새로 넣지 않는다. 따라서 같은 경로·같은 입력·같은 버전이면 manifest와 normalized artifact의 경로와 SHA-256이 같다.

## manifest 스키마

top-level 필수 키:

| 키 | 결정 규칙 |
|---|---|
| `manifest_schema_version` | `dnf_corpus_manifest_v3.0` |
| `manifest_id` | `manifest_id`를 제외한 canonical JSON payload의 SHA-256 |
| `corpus_name` | 현재 corpus는 `dnf_official` |
| `snapshotter_version` | snapshot 생성 규칙 버전 |
| `artifacts` | `source_name`, `source_path` 순으로 정렬한 snapshot 항목 |
| `total_row_count` | 모든 snapshot의 JSONL 행 수 합 |

snapshot 항목 필수 키:

| 키 | 결정 규칙 |
|---|---|
| `snapshot_id` | 원본 파일 전체 SHA-256 기반 content-addressed ID |
| `source_name` | 파일명에 쓸 소문자 영문·숫자·underscore 이름 |
| `source_path` | 읽기 전용 v2 입력 경로 |
| `snapshot_path` | v3 immutable 복사본 경로 |
| `sha256` | 원본과 snapshot 양쪽에서 동일해야 하는 파일 전체 SHA-256 |
| `fetched_at` | raw 행의 유일한 `metadata.collected_at`; 없거나 둘 이상이면 실패 |
| `parser_version` | 원본을 만든 수집 parser 버전 |
| `row_count` | 빈 줄을 제외하고 정상 파싱된 JSON 행 수 |
| `byte_count` | 원본 파일 바이트 수 |

v2 수집기는 parser version을 기록하지 않았다. 이를 추정하지 않고 각각 `collect_guide_selenium.legacy-v2-unversioned`, `collect_official_docs.legacy-v2-unversioned`로 명시한다.

## `DocumentV3` 필드 결정 규칙

### `category_path`

1. `metadata.official_section`을 첫 요소로 둔다.
2. 게임 가이드는 `metadata.guide_category`, 그 밖의 문서는 `metadata.category`를 빈 값이 아닐 때만 다음 요소로 둔다.
3. 중복·빈 요소는 넣지 않는다.
4. 둘 다 없을 때만 `source_kind` 하나를 fallback으로 사용한다.

따라서 기존 가이드의 상세 category가 누락된 경우 `['guide']`로 남는다. 존재하지 않는 상세 category를 추정해 채우지 않는다.

### `source_kind`

| v2 `doc_type` | v3 `source_kind` |
|---|---|
| `game_guide` | `game_guide` |
| `patch_note` | `patch_note` |
| `event` | `event` |
| `notice` | `notice` |
| `account_payment` | `account_policy` |
| `bug_known_issue` | `known_issue` |

알 수 없는 `doc_type`은 `metadata.official_section`의 알려진 값으로 한 번 더 매핑하고, 그래도 없으면 원래 값 또는 `unknown`을 사용한다.

`source_kind`는 저장소 이름이나 시간 상태가 아니라 문서의 의미 유형이다. 다음 discovery 사이클에서는 `maintenance`, `hotfix`, `enforcement_notice`, `general_notice`, `preview_patch`, `faq`, `shop_product`, `monthly_item`, `item_catalog`, `enchant`, `roadmap_statement`가 추가될 수 있다. `preview_patch`·`roadmap_statement`처럼 기본 검색에서 제외되는 유형도 삭제하지 않고 별도 policy로 필터링한다.

하나의 문서는 여러 index/store에 투영될 수 있지만 `document_id`와 revision 관계는 하나만 유지한다. 확정 출처·저장소·노출 정책은 [source_discovery_registry.md](source_discovery_registry.md)를 따른다. 현재 v2 raw normalizer의 여섯 유형 매핑과 이미 생성된 artifact는 변경하지 않는다.

### `canonical_url`

- `http` 또는 `https` URL만 허용한다.
- scheme과 host를 소문자로 만든다.
- fragment는 제거한다.
- query parameter는 key/value 순으로 정렬한다.
- root가 아닌 path의 마지막 `/`는 제거한다.
- query parameter를 임의로 삭제하거나 `http`를 `https`로 바꾸지 않는다.

### `content_hash`

다음 안정적 payload를 key 정렬·공백 없는 UTF-8 JSON으로 직렬화한 SHA-256이다.

```text
source_type
doc_type
title
published_at
effective_start
effective_end
tags
text
metadata에서 collected_at만 제외한 값
```

`doc_id`, `source_url`, `metadata.collected_at`은 제외한다. 같은 내용을 다시 수집한 것만 같은 hash로 보고, 본문뿐 아니라 유효기간·category 같은 의미 있는 metadata 변경도 새 revision으로 잡는다.

### `revision_id`, `document_id`, revision 관계

- revision identity는 `SHA-256(canonical_url + newline + content_hash)`다.
- `document_id`와 `revision_id`는 같은 identity hash에 서로 다른 prefix를 붙인다.
- 같은 canonical URL·같은 content hash 관측은 하나로 합치며, 가장 최근 `fetched_at`의 snapshot을 provenance로 사용한다.
- 같은 canonical URL·다른 content hash는 `fetched_at` 순으로 연결하고, 새 행의 `supersedes_document_id`가 바로 이전 revision의 `document_id`를 가리킨다.
- 다른 content hash가 같은 URL에서 같은 `fetched_at`으로 관측되면 순서를 추정하지 않고 실패한다.

content-addressed ID이므로 입력 순서를 바꾸거나 동일 revision을 다시 수집해도 ID는 바뀌지 않는다.

### `status`

`status`는 artifact 재현성을 위해 현재 실행 날짜가 아니라 해당 revision의 `fetched_at` 날짜 기준이다.

1. 더 최신 revision이 있으면 `superseded`
2. 날짜 파싱 실패 또는 `valid_from > valid_to`면 `unknown`
3. `valid_from`이 `fetched_at` 날짜보다 뒤면 `upcoming`
4. `valid_to`가 `fetched_at` 날짜보다 앞이면 `expired`
5. 그 밖의 최신 revision은 `current`

여기서 `current`는 “snapshot 시점의 최신 revision이며 유효기간 밖으로 판정되지 않음”을 뜻한다. 질의 시점의 이벤트 활성 여부는 후속 구조화 저장소와 검색 필터에서 다시 계산해야 한다.

### 나머지 provenance 필드

- `fetched_at`: 선택된 snapshot manifest의 수집 시각을 그대로 보존한다. legacy 값에 없던 timezone을 추정해 덧붙이지 않는다.
- `parser_version`: 현재 변환기는 `dnf_v2_raw_normalizer_v3.0`이다.
- `raw_source_path`: v2 경로가 아니라 immutable v3 snapshot 경로다.
- `authority`: v2 `source_type`을 사용하며 빈 값일 때만 `official`로 둔다.

## 실행과 재현성 확인

```powershell
python -m src.v3.build_corpus
python -m src.v3.build_corpus
python -m unittest tests.v3.test_audit_corpus tests.v3.test_build_corpus
```

두 번째 build는 파일을 덮어쓰지 않고 같은 content-addressed artifact를 확인·재사용해야 한다.
