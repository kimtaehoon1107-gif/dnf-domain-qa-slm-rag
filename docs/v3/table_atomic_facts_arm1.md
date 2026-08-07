# v3.2 Table Row Atomic Facts — Arm 1 Contract

Status: development-only A/B, not canonical, not runtime-promoted.

> 2026-07-21 후속 결정: 이 문서의 Arm 1.2 artifact는 기존 95문항 무회귀 확인 후
> 사용자 명시 승인으로 v3 기본 개발 runtime/canonical view에 승격됐다. 새 sealed
> canary는 실행하지 않았으며 production-ready 승격은 아니다. 현재 상태는
> `docs/v3/v3_2_runtime_promotion.md`가 supersede한다.

## Purpose and lineage

Arm 1 tests one narrow hypothesis: a table value row should remain retrievable when its cells do not repeat the surrounding subject or attribute words. It adds row-level children beside the frozen v3.1 parent chunks; it does not rewrite, clean, delete, or rechunk the dirty canonical corpus.

The immutable parent input is `chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl`. Every output records this SHA-256 and is content-addressed.

## Bounded Arm 1 scope

Only complete `[TABLE] ... [/TABLE]` blocks in DOM-text chunks are eligible. Arm 1 is limited to `dnf_game_guide`, `dnf_seria_shop`, `dnf_monthly_item`, and `dnf_account_policy`, and to tables whose caption, heading, or header identifies cost/price, sale period, deletion date, validity/effective period, or a directly related attribute. Visual-OCR rows and incomplete table fragments are excluded.

This is a bounded failure-directed parser experiment, not a full conversion of every table in the corpus. Later display-cleaning, duplicate-family, temporal-contract, and broad table-parsing arms are explicitly out of scope.

## Additive schema

Each atomic fact has these required fields:

- `table_id`, `row_id`, `fact_id`
- `subject`, `attribute`, `value`, `unit`
- `source_chunk_id`
- `start_offset`, `end_offset`

`start_offset` and `end_offset` are offsets into the frozen source chunk's `display_text`. The exact invariant is:

```text
source_chunk.display_text[start_offset:end_offset] == row_text
```

The artifact also stores `parent_document_id`, parent-document offsets, table caption/heading, source and temporal metadata, the exact `row_text`, and an enriched `retrieval_text`. The enriched field may repeat subject and attribute for retrieval, but citations always slice the unchanged source row. Facts sharing one physical row share `row_id` and offsets.

The row subject preserves entity-bearing identity columns, including spacing variants such as `아이템 명칭`, commerce labels such as `판매 아이템` and `구매 가능 아이템`, and part labels such as `아바타 부위`. Newly recognized aliases remain available as exact source values as well as enriching the subject, so this parser revision does not delete a previously emitted cell value merely to improve retrieval identity.

Tables whose data repeats the complete header row are treated as structurally ambiguous entity-column matrices. Their exact facts remain in the additive artifact, but `table_review_required=true` also forces `review_required=true`, so they cannot enter the default sidecar until a separate orientation parser validates their attribute semantics.

Parent chunks remain the authoritative display and citation context. When a row child is selected, the UI or answer layer must expose both the exact row and its parent table/chunk context.

## Table-group completeness output

A row child is a retrieval seed, not permission to answer with only one cell. After a table seed is selected, the Arm 1.1 assembler groups by `table_id`, restores every `row_id` in source order, and emits every atomic attribute available for those rows. The ordinary distinct-chunk cap does not apply inside this already-selected table; increasing global retrieval K is not allowed as a substitute.

For a specific query such as `서약 결정 초월 가격`, only the best-matching table in the preferred parent is expanded. When a short query such as `초월 가격` equally identifies multiple cost tables in that parent, each table is displayed separately rather than silently mixing their rows. Every rendered row retains its exact source-chunk slice and parent table context. This output is still extractive: it may format exact cell values as a Markdown table, but it may not paraphrase or invent a missing cell.

## Determinism and identity

- Rows are reconstructed only from mutually consistent overlapping DOM-text chunks.
- Uncovered parent-offset gaps remain counted for audit, but are represented as line breaks during reconstruction so headings on either side cannot be concatenated. Gap sentinels such as `U+FFFD` may not enter captions, subjects, or retrieval text.
- IDs are SHA-256 over stable lineage and normalized structural fields.
- Output rows are sorted by parent offsets, source chunk, subject, attribute, and fact ID.
- Re-freezing identical inputs and parser version must yield identical JSONL bytes and artifact SHA-256.
- Existing parent chunk IDs and all evaluation gold contents remain unchanged. Mapping a child to `source_chunk_id` is an evaluation ID correspondence, not a gold edit.

## Additive retrieval A/B

The dirty parent candidate pool and frozen assembler output are the baseline. Arm 1 builds a row-child sidecar index and unions eligible row children with the baseline; it never evicts or reorders the frozen parent pool. This prevents the candidate-depth boundary regression observed in the hygiene experiment.

Runtime eligibility inherits the source row's existing temporal metadata and applies the current-question policy: `default_exposure=true`, current/active status, no review-required content, and a valid date interval. Preview, expired, superseded, or future-invalid children cannot be exposed by Arm 1.

The development demo adds two stricter integration guards. A table child must belong to a parent document already cited for the same requirement, and current-mode lookup must also pass the global temporal overlay for that parent. Source-level routing alone is not permission to attach a table from another product or revision. Historical/preview modes may reuse only their already-cited parent; they do not broaden table search to the whole source.

The A/B uses existing dev and authored-canary questions. Gold chunk IDs are used only for mechanical scoring; they are unavailable to retrieval or selection. The separate `초월 가격` probe is a documented diagnostic, not a new benchmark question.

## Promotion gate

Arm 1 becomes only a v3.2 canonical candidate if all conditions hold:

1. Gold evidence content loss = 0.
2. Exact row-offset validity = 100%.
3. Candidate recall does not regress.
4. Grounded answers remain at least 73.
5. New false-full answers = 0.
6. Temporal/revision/preview leakage = 0.
7. Replacement characters in caption, subject, and retrieval text = 0.

The report must additionally state whether the transcendence value row is recovered, whether either frozen sibling-attribute failure is recovered, and whether additive children perturb the parent ranking. Passing this gate does not promote the arm: one new sealed canary run is still required. Any failed condition leaves dirty v3.1 canonical and freezes Arm 1 as development-only NO-GO.
