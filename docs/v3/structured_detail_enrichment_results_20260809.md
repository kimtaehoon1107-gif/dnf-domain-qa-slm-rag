# Structured detail enrichment results (2026-08-09)

## 1. Scope and decision

This round added a separate structured-detail enrichment experiment. It did not
change or promote the canonical corpus, runtime, BM25/BGE-M3 indexes, Qwen,
sealed A6 artifacts, existing OCR chunks, or `app/`.

The failed-K2 new-corpus inputs remain unpromoted and were not added by this
commit. The enrichment CLIs therefore require their ledger and document paths
explicitly instead of treating those experimental inputs as defaults. The
content-addressed detail responses and parsed evidence needed for review and
tests are self-contained under `data/v3/structured_details/`.

Decision: **GO for structured HTML enrichment artifacts; no runtime promotion.**

The supported rule is generic: a local parent snapshot containing
`eventRewardPop(<numeric id>)` maps to the official endpoint
`/POP/common/event/event_reward_item.php?id=<numeric id>`. There is no parent
URL, title, `michaela`, or `808` branch in production code.

## 2. P0 local-only scan

All 998 paths in the 2026-08-07 detail collection ledger existed locally and
were scanned without recollecting the parent pages.

| signal | references | parent documents | same-host official | external/other | unique URLs | duplicate references | action |
|---|---:|---:|---:|---:|---:|---:|---|
| `eventRewardPop(...)` | 25 | 17 | 25 | 0 | 25 | 0 | supported and collected |
| literal `window.open(...)` | 2,540 | 847 | 1,692 | 848 | 4 | 2,536 | shared navigation; ambiguous, not collected |
| `iframe src` | 1,008 | 998 | 2 | 1,006 | 10 | 998 | analytics/login residue; not collected |
| literal `$.ajax({url: ...})` | 281 | 281 | 281 | 0 | 1 | 280 | shared request; ambiguous, not collected |
| detail-like anchors | 102 | 73 | 17 | 85 | 34 | 68 | broad links; not automatically collected |
| literal `fetch` / `axios` / data API attributes | 0 | 0 | 0 | 0 | 0 | 0 | none |
| embedded JSON script | 0 documents | | | | | | none |

The only locally demonstrated, low-ambiguity structured-detail contract was
the event reward popup. Its 25 endpoints were all same-host official URLs,
required no authentication, and had no duplicate detail URL.

The parent snapshot for `https://df.nexon.com/pg/michaelaevent` was detected by
the same rule and produced reward id `808`; it was not selected by URL or name.

The initial coarse empty-information scan found 9 documents whose
reward/cost/material/type heading lacked visible values and coexisted with CSS
assets. The implemented section-scoped detector removed coarse false signals
and recorded 10 incomplete visual sections in 7 documents.

## 3. P1 failing tests before implementation

`tests/v3/test_structured_detail_tables.py` was added before the modules.
The first run failed during collection with:

```text
ModuleNotFoundError: No module named 'src.v3.collect_structured_details'
```

After the first parser implementation, an additional real-shape regression
test reproduced a child row whose description cell used `colspan=2`. It failed
because the description was incorrectly copied into `mission`:

```text
assert '하위 아이템 설명' == '1주차 클리어'
```

The parser was then narrowed to inherit the parent mission only for the
official child-row marker. A second regression test verified that a two-column
incomplete table containing a child row remains incomplete without raising.

## 4. Changed files

- `src/v3/discover_structured_details.py`
  - Discovers numeric event reward references from local HTML.
  - Rejects non-allowed hosts.
  - Diagnoses incomplete information sections at section scope.
- `src/v3/collect_structured_details.py`
  - Fetches only newly discovered official detail endpoints.
  - Deduplicates by detail URL and stores immutable responses with URL, time,
    status, retry count, byte count, and SHA-256.
  - Links each response to the parent document, revision, and lineage.
- `src/v3/parse_structured_detail_tables.py`
  - Preserves header and row order, source text, normalized text, colspan,
    rowspan, explicit parent/child rows, and restorable HTML locators.
  - Emits complete tables separately from atomic rows.
- `tests/v3/test_structured_detail_tables.py`
  - Covers generic discovery, official-host enforcement, row/column binding,
    incomplete tables, visual-only sections, and the real 23-row popup.

No existing parser was rewritten.

## 5. Collection and parsed artifacts

Discovery:

- `data/v3/structured_details/structured_detail_discovery_eace836352656a46192bf1f4321b6a9338ddeb06376aedde3a4858ad9926242e.jsonl`
- `data/v3/structured_details/visual_section_diagnostic_9939b351b19e8386ff1945f878bca6225b3cf67195742630e0b5b36859ed9f28.jsonl`
- `data/v3/structured_details/structured_detail_discovery_manifest_f235ad9e8289cbf31680b06ba9b22df5038eeb8b02caeac249e7971b5eb085db.json`

Collection:

- 25 unique endpoint fetches, 25 HTTP 200, 0 failures, 0 retries masked as
  success, 0 missing parent metadata.
- `data/v3/structured_details/structured_detail_collection_d37f2bc08124f980accfda10109fbc00f37de7f86c8efdba0b7eb63886cc7fa9.jsonl`
- `data/v3/structured_details/structured_detail_collection_manifest_495b6fe6ff58c1661a72125a66b559735e6b82c684a0f2b82860a400ac060589.json`

Parsing:

- 25 tables, of which 3 satisfy the strict three-column reward contract and
  22 remain `complete=false`.
- 466 atomic rows.
- 1,025/1,025 cell locators restored exactly.
- `data/v3/structured_details/structured_detail_tables_c8a72b164e99a2256e59f7970cc2484aafca54f65f4599c52009fa8ca526513b.jsonl`
- `data/v3/structured_details/structured_detail_atomic_rows_de28e6f533a5152f76afbddb5065c30d03e52d20bb27111d815c7c6c32ea7951.jsonl`
- `data/v3/structured_details/structured_detail_tables_manifest_2f0b95322275090a4ace370edf6f599eb7fcced46c8c58932849c5a0ad4b543a.json`

## 6. Michaela 23-row result

The official snapshot SHA-256 is
`f724b6122fdcbfce89aa635637f2fccd02f6afb09bc2f26b309e9c62ebaa443b`.

| check | result |
|---|---:|
| complete tables for reward id 808 | 1 |
| headers | `아이템 명`, `아이템 설명`, `미션` |
| rows | 23 |
| account mission parent rows | 3 |
| 1-week reward group rows | 5 |
| 2-week reward group rows | 2 |
| TOP 20 group rows | 7 |
| hard special-auction group rows | 6 |
| explicit child rows | 16 |
| cell locators restored | 69/69 |

The 23 rows include the three account missions, first/second-week character
rewards, TOP 20 rewards, and the hard special-auction
`[무너진 성자 미카엘라] 치장 선택 상자` plus its five child choices.

Source spelling is preserved. For example, the source string
`되찾은 성자의 빛 오라 상자 상자` was not silently corrected.

## 7. Complete table and atomic-row example

The complete table is stored separately from the parent DOM and OCR text. A
representative atomic row is:

```json
{
  "row_index": 17,
  "item_name": "[무너진 성자 미카엘라] 치장 선택 상자",
  "mission": "미카엘라 : 종언서(하드) 특별 경매 이벤트",
  "parent_row_index": null,
  "row_relation": "independent",
  "trade_type": "계정귀속",
  "deletion_at": null,
  "detail_snapshot_sha256": "f724b6122fdcbfce89aa635637f2fccd02f6afb09bc2f26b309e9c62ebaa443b"
}
```

Each field also stores `source_text`, `normalized_text`, rowspan/colspan, and a
cell locator. Child choices point to row 17 and inherit its mission through the
parent mission locator rather than copying their `colspan=2` description.

## 8. Visual-section result

The section-scoped detector found 10 incomplete sections in 7 documents:

- 9 sections have an official structured detail available and are therefore
  not OCR candidates.
- 1 section, `레이드 보상` in
  `https://df.nexon.com/pg/fallensaintmichaela`, has no structured detail and
  remains the only OCR candidate.
- Every diagnostic row is `review_required=true` and
  `default_exposure=false`; these flags do not mutate the existing corpus.

No Windows OCR text was promoted.

## 9. Tests and false-full accounting

Targeted tests:

```text
7 passed
```

Full v3 regression:

```text
1,277 passed / 2 failed / 67 subtests passed
```

The two failures are the previously known content-addressed manifest SHA
exemptions in decomposed hybrid and unified runtime. No new regression failed.

New runtime false-full: **0**, because this enrichment is not connected to the
runtime. Parser contract false-complete: **0**; 22 tables that did not satisfy
the strict reward-table schema were kept incomplete. `complete=true` is not yet
used to authorize full answers in the product runtime.

## 10. Next step

The structured HTML path is complete for this round. A separate OCR arm is
still needed only for the remaining `fallensaintmichaela` reward section. That
arm should start only after reviewed visual gold exists and must preserve
crops, word/row bounding boxes, and row/column relationships with zero false
structure. It was not implemented in this round.
