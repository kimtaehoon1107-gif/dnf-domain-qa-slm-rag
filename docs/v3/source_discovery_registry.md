# DNF RAG v3 공식 출처 discovery registry 계약

## 결정 상태와 범위

이 문서는 source-discovery 계약과 2026-07-17 재freeze 결과를 함께 기록한다. `src/v3/discover_sources.py`가 공식 listing을 실제로 순회했고, detail 본문은 수집하지 않았다.

실제 실행에서 공지 518/518페이지, 업데이트 95/95페이지, FAQ 16/16페이지, 세리아 상점 판매 중 5/5페이지를 순회했다. 세리아 상점 종료 목록은 종료 12개월 window보다 오래된 항목만 있는 첫 완전 페이지에서 정지했다. 종료 이벤트는 `event/list?categoryType=3`, 과거 이달의 아이템은 세리아 상점 종료 목록의 `searchKeyword=이달` 25/25페이지를 추가로 순회했다. blocked·partial 출처는 없었다.

고유 canonical URL 13,214개 중 collection policy eligible은 982개였다. 기존 DocumentV3 188개와 비교한 eligible coverage는 181개, missing eligible은 801개였다. listing observation 중복은 610건이며, 이 중 18건은 서로 다른 listing이 같은 canonical URL을 가리킨 경우다.

산출물:

- registry: `data/v3/discovery/source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl`
- manifest: `data/v3/discovery/source_registry_manifest_4cbd8c441fd694ec16ad30b6b42c4c6f28326dc9a768d883399419ef87ee9ea2.json`
- coverage: `reports/v3/source_discovery_coverage_808b68170bcf209dcbeb871efe249fa6eb151dc9efdb4ab887a8a5e137c0ff45.json` 및 `.md`

이 사이클이 수행한 작업은 다음 세 가지다.

1. 공식 출처 registry를 기계 판독 가능한 artifact로 고정
2. list/category/revision/API pagination을 통한 URL discovery snapshot 생성
3. 발견 URL과 현재 v3 수집 URL을 비교한 coverage report 생성

detail parser, chunker, BM25, Router, decomposition, Evidence Selector, Generator, Verifier, RAFT/LoRA는 이 discovery 사이클의 범위 밖이다. 모든 출처의 discovery scope가 측정되어 다음 source별 detail collection 설계 판정은 `GO`다.

## 분리 원칙

- discovery와 detail collection을 별도 실행 단계로 둔다. 특히 기존 `collect_official_docs.py`의 기본 `--pages 1`을 discovery completeness로 간주하지 않는다.
- `source_kind`는 문서의 의미 유형이고, index/store는 파생 저장소다. 한 문서가 여러 저장소에 투영돼도 `document_id`를 새로 만들지 않는다.
- 현재/예정/만료/대체 여부는 `status`, `valid_from`, `valid_to`로 표현한다. `source_kind`에 시간 상태를 섞지 않는다.
- 기본 검색 노출 여부는 별도 retrieval policy로 결정한다. `status`만 있으면 안전하다고 가정하지 않는다.
- discovery URL 원장은 immutable snapshot으로 보존하고, detail 수집 실패가 있어도 발견 URL을 삭제하지 않는다.
- URL별 detail 수집 결과는 `success`, `failed`, `not_attempted`, `excluded_by_scope`를 구분한다.

## frozen registry row 계약

기계 판독 registry의 각 URL row는 다음 필드를 가진다.

```text
source_id
source_kind
listing_url
canonical_url
canonical_url_kind
source_item_id
title
category
discovered_at
published_at
period_start
period_end
page_number
eligible_for_collection
eligibility_reason
status
default_exposure
is_pinned
discovery_parser_version
```

- 상대 기간은 실행 때 고정한 `discovered_at` 기준의 절대 cutoff로 해석해 manifest의 `policy_context`에 기록한다.
- 현재 시즌 시작일은 업데이트 제목의 가장 최근 `시즌 N Act 1`에서 판정했고, 이번 freeze에서 `2026-04-22`로 기록됐다. CLI `--season-start`로 명시 재현할 수 있다.
- list pagination 종료 조건, 중복 URL 제거 전후 수, HTTP/parser 오류를 source별로 기록한다.
- FAQ는 개별 detail href가 없는 inline item이므로 `faq_no`를 사용한 deterministic synthetic locator에 `canonical_url_kind=synthetic_inline_item_locator`를 붙인다.

## 확정 source registry

### 1. 공지사항

- `source_id`: `dnf_notice`
- entry URL: `https://df.nexon.com/community/news/notice/list`
- discovery: 전체 list 페이지를 끝까지 순회한 뒤 detail URL 원장을 생성
- 허용 `source_kind`와 저장소:

| `source_kind` | 대상 저장소 |
|---|---|
| `maintenance` | `maintenance_store` |
| `known_issue` | `known_issue_index` |
| `hotfix` | `notice_index` |
| `account_policy` | `account_policy_index` |
| `enforcement_notice` | `notice_index` |
| `general_notice` | `notice_index` |

이 discovery 단계의 분류는 list category와 제목 signal만 사용한다. 점검, 오류, 패치, 제재, 계정·보안 signal에 해당하지 않는 공지는 `general_notice`로 두고 `eligibility_reason=listing_metadata_no_specific_signal`을 기록한다. detail 본문 수집 후 분류를 다시 확정해야 하며, discovery 분류를 본문 확정 라벨로 간주하지 않는다.

수집 범위는 최근 12개월과 기간 밖이라도 여전히 유효한 고정 공지다. discovery 자체는 전체 페이지를 대상으로 하며, 범위 밖 URL도 `excluded_by_scope`로 원장에 남긴다.

### 2. 업데이트

- `source_id`: `dnf_update`
- entry URL: `https://df.nexon.com/community/news/update/list`
- discovery: 전체 대상 기간의 list pagination
- 분리:

| 구분 | `source_kind` | 저장소 | 기본 현재 검색 |
|---|---|---|---|
| 라이브 서버 업데이트 | `patch_note` | `patch_note_index` | 포함 가능 |
| 퍼스트 서버 업데이트 | `preview_patch` | `preview_patch_index` | 제외 |

수집 범위는 명시적으로 기록된 현재 시즌 시작일 이후 전체다. 퍼스트 서버 문서는 보존하지만, 라이브 반영이 확인되기 전에는 현재 사실을 답하는 기본 검색에 노출하지 않는다.

### 3. 이벤트

- `source_id`: `dnf_event`
- entry URL: `https://df.nexon.com/community/news/event/list`
- 종료 archive URL: `https://df.nexon.com/community/news/event/list?categoryType=3`
- discovery: 진행 중·예정 전체와 종료 후 6개월 이내
- `source_kind`: `event`
- 저장소: `event_store`
- 기본 검색: `current`, `upcoming`만 시간 의도에 맞게 노출; `expired`는 기본 현재 검색에서 제외

구조화 projection 필수 필드:

```text
event_name
start_at
end_at
eligibility
reward
claim_method
status
source_document_id
evidence_chunk_id
```

`source_document_id`와 `evidence_chunk_id`가 없는 event fact는 배포하지 않는다.

종료 archive 경로는 현재 이벤트도 함께 반환하므로 canonical URL로 중복 제거한다. 2026-07-17 재freeze에서 event observation 423건을 읽어 고유 URL 362개로 고정했고, 6개월 정책 window eligible은 27개였다.

### 4. 게임 가이드

- `source_id`: `dnf_game_guide`
- entry URL: `https://df.nexon.com/guide`
- discovery: 현재 공개된 모든 `guide?no=` URL 재발견
- `source_kind`: `game_guide`
- 저장소: `game_guide_index`
- 수집 범위: 현재 공개 전체

coverage report에서 기존 125개와 canonical URL로 대조하고, 신규·누락·더 이상 발견되지 않는 URL을 분리한다. list/category 구조에서 `category_path`와 `updated_at`을 복구하되 추정값은 넣지 않는다.

### 5. 고객센터 FAQ

- `source_id`: `dnf_faq`
- entry URL: `https://df.nexon.com/customer/faq`
- discovery category:

```text
아이디정보/보안
설치/실행
게임문의
복구
결제
PC방
이벤트
던파ON
```

- `source_kind`: `faq`
- 기본 저장소: `faq_index`
- 계정·보안·결제 정책 성격의 FAQ: 같은 `document_id`를 `account_policy_index`에도 투영
- 수집 범위: 현재 공개 전체

이벤트성 FAQ는 `valid_from`, `valid_to`, `status`가 판정되지 않으면 current 검색용으로 승격하지 않는다.

### 6. 운영정책

- `source_id`: `dnf_account_policy`
- entry URL: `https://df.nexon.com/customer/policy/home?type=1`
- discovery: 현재 운영정책과 시행일별 과거 revision 전체
- `source_kind`: `account_policy`
- 저장소: `account_policy_index`
- 수집 범위: 현재본과 발견 가능한 모든 시행일 revision

과거본은 `superseded` revision으로 보존한다. 현재 정책 질문의 기본 검색에서는 최신 current revision만 노출하고, 사용자가 과거 시행일을 명시한 경우에만 과거본을 검색한다.

### 7. 세리아 상점

- `source_id`: `dnf_seria_shop`
- entry URL: `https://df.nexon.com/community/news/seriashop/list`
- discovery: 판매 중 전체와 종료 후 12개월 이내
- `source_kind`: `shop_product`
- 저장소: `shop_price_store`
- 기본 검색: 판매 종료 상품은 현재 판매 질문에서 제외

구조화 projection 필수 필드:

```text
product_name
price
currency
sale_start
sale_end
sale_status
components
deletion_at
source_document_id
evidence_chunk_id
```

### 8. 이달의 아이템

- `source_id`: `dnf_monthly_item`
- entry URL: `https://df.nexon.com/community/news/monthlyitem/`
- 과거 archive URL: `https://df.nexon.com/community/news/seriashop/list?category=2&searchKeyword=이달`
- `source_kind`: `monthly_item`
- canonical 저장소: `shop_price_store`
- `store_subtype`: `monthly_item`

별도의 `monthly_item_store`에 원본 사실을 중복 저장하지 않는다. 필요하면 `shop_price_store`의 subtype view로 제공한다. 판매 기간, 상점 판매가, 거래 타입, 삭제일과 provenance 두 필드를 필수로 구조화한다. 수집 기간은 상점 정책과 동일하게 판매 중 전체와 종료 후 12개월 이내다.

과거 archive는 세리아 상점 종료 카테고리의 `searchKeyword=이달` 25페이지를 끝까지 순회한다. 재freeze에서 현재 landing과 과거 검색 결과를 합쳐 고유 URL 147개, 12개월 정책 window eligible 14개로 고정했다. 과거 항목은 `expired`, `default_exposure=false`로 보존한다.

### 9. 장비·마법부여·아이템 catalog

entry URL:

```text
https://df.nexon.com/guide/equipment
https://df.nexon.com/guide/equipment/enchant
https://developers.neople.co.kr/contents/apiDocs/df
```

| `source_id` | 내용 | `source_kind` | 저장소 |
|---|---|---|---|
| `dnf_equipment_guide` | 장비·세트·획득처 안내 | `item_catalog` | `item_catalog_store` |
| `dnf_enchant_guide` | 마법부여 안내 | `enchant` | `enchant_store` |
| `neople_item_api` | 아이템 상세·상점 판매·획득처·세트 정보 | `item_catalog` 또는 `enchant` | 해당 store |

공식 웹 문서와 Neople Open API provenance는 `authority`, `canonical_url`, `source_snapshot_id`로 구분한다. API endpoint·요청 parameter·응답 schema version을 snapshot manifest에 기록한다.

경매장 시세와 사용자 캐릭터 상태는 corpus snapshot에 넣지 않는다. 두 유형은 freshness와 사용자별 상태가 필요한 향후 실시간 API route로 분리하며 이번 discovery coverage 분모에서도 제외한다.

## 별도 보관과 제외

### 별도 보관

- 개발자노트는 `source_kind=roadmap_statement`, `roadmap_statement_index`로만 보관한다.
- roadmap/예고 표현은 current fact와 합치지 않으며 기본 현재 사실 검색에서 제외한다.

### 공식 사실 코퍼스 제외

- 오늘의 던파
- 던파매거진
- 사용자 커뮤니티 공략
- 위키
- 블로그
- 기타 커뮤니티

제외 URL을 발견했다면 조용히 버리지 않고 exclusion reason과 건수를 coverage report에 남긴다.

## 기본 검색 노출 정책

다음 문서는 보존하되 status/time/source policy 없이 기본 검색에 노출하면 안 된다.

| 문서 | 보존 | 기본 현재 검색 |
|---|---|---|
| 종료 이벤트 | 예 | 제외 |
| 과거 운영정책 revision | 예 | 제외 |
| 퍼스트 서버 업데이트 | 예 | 제외 |
| 종료 상품 | 예 | 제외 |
| 개발자노트·roadmap | 예 | 제외 |

이 정책은 향후 index build와 retrieval 양쪽에서 검증한다. 이번 사이클에서는 index를 만들지 않는다.

## coverage report 계약

### 비교 단위

- 모든 URL은 `DocumentV3`와 같은 canonicalization 규칙을 적용한다.
- 발견 URL과 현재 수집 URL은 canonical URL의 집합으로 비교한다.
- 한 문서가 여러 store에 투영돼도 한 번만 센다.
- raw discovery 전체와 collection window 적용 후 eligible 집합을 모두 보고한다.

source별 필수 지표:

```text
source_id
discovered_url_count
eligible_discovered_url_count
currently_collected_url_count
covered_url_count
missing_url_count
collected_not_currently_discovered_count
duplicate_discovered_url_count
excluded_by_scope_count
unclassified_url_count
discovery_error_count
coverage_rate
```

집합 정의:

```text
covered_urls = eligible_discovered_urls ∩ currently_collected_urls
missing_urls = eligible_discovered_urls - currently_collected_urls
collected_not_currently_discovered_urls = currently_collected_urls - discovered_urls
coverage_rate = |covered_urls| / |eligible_discovered_urls|
```

분모가 0이면 coverage를 1.0으로 만들지 않고 `not_measured`로 기록한다. `collected_not_currently_discovered`는 삭제 대상으로 간주하지 않는다. 종료·비공개·URL 이동·discovery 실패 가능성을 각각 조사한다.

보고서에는 count뿐 아니라 다음 URL 목록을 별도 artifact로 남긴다.

```text
discovered_urls
eligible_discovered_urls
covered_urls
missing_urls
collected_not_currently_discovered_urls
duplicate_url_groups
excluded_urls_with_reason
unclassified_urls
failed_pages
```

## discovery artifact 명명

```text
data/v3/discovery/source_registry_{registry_sha256}.jsonl
data/v3/discovery/source_registry_manifest_{manifest_sha256}.json
reports/v3/source_discovery_coverage_{report_json_sha256}.json
reports/v3/source_discovery_coverage_{report_json_sha256}.md
```

registry와 manifest 파일명의 해시는 해당 파일 bytes의 SHA-256 전체 64자리다. Markdown 보고서는 같은 JSON report snapshot의 해시로 연결한다. registry row를 결정론적으로 정렬하고 고정한 `discovered_at`으로 다시 freeze하면 같은 registry·manifest 해시가 나와야 한다.

## 실행 검증과 다음 승격 조건

1. registry의 모든 source가 discovery 실행 또는 명시적 실패 상태를 가진다. **충족**
2. 공지 `--pages 1` 의존 없이 전체 pagination 종료 근거를 기록한다. **충족**
3. source별 발견·eligible·covered·missing 집합이 재현된다. **충족**
4. 누락 URL 목록과 discovery/parser 오류가 분리된다. **충족**
5. current v3 raw/manifest/DocumentV3 artifact와 v2 입력 hash가 바뀌지 않는다. **충족**
6. frozen blind를 열거나 검색하지 않는다. **충족**
7. detail 대량 수집, chunker, BM25, Router로 확장하지 않는다. **충족**

종료 이벤트와 과거 이달의 아이템 archive까지 실측해 blocked·partial source가 0이므로, 다음 source별 detail collection 설계 단계는 **GO**다. 이 GO는 discovery scope 완료를 의미하며, 종료 이벤트·과거 정책·퍼스트 서버·종료 상품의 `default_exposure=false` 제약을 풀지 않는다.
