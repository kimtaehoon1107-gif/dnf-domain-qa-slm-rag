# Table prompt compression round

## Scope

- Model: `qwen3-8b:ctx8192`
- Retrieval and candidate pools: unchanged
- Corpus and table-fact artifacts: unchanged
- Changed path: split-schema table generation only
- Non-table typed evidence-ref prompt: unchanged
- Evaluation role: adaptive diagnostic, not a new generalization score

## Change

For table-mode requirements, candidate metadata and the requirement-filtered
table rows are retained, while full candidate `display_text` is omitted from
the model prompt. The server continues to hold the full chunks and verifies
the selected row against the original coordinates.

The table selector also treats values from row-key attributes such as
`판매 목록`, `판매 물품`, `아이템명`, and `상품명` as row-subject candidates.

For date, date-range, and datetime table values, ISO and Korean forms are
compared after normalization. A normalized model value is exposed only when
the exact cited row contains one matching requested-attribute value; the
server then restores that exact source value.

## Slot 49

Question:

```text
프리미엄 코인샵의 트로피컬 바캉스 무기 아바타 상자는 언제 삭제돼?
```

Selected row:

```text
| [프리미엄 코인샵]트로피컬 바캉스 무기 아바타 상자 | 2개 | 계정당 5회 | 2026년 8월 27일 06시 |
```

| Run | Input tokens | Output tokens | Latency | Result |
|---|---:|---:|---:|---|
| Before compression, isolated | 7,957 | 228 | 23.45s | correct |
| Before compression, seven-case run | 7,958 | 228 | 17.13s | correct |
| Compressed, isolated | 2,578 | 146 | 15.61s | correct |
| Compressed, seven-case run | 2,489 | 149 | 13.14s | semantically correct ISO value, blocked by old string verifier |
| Compressed, after typed table normalization | 2,489 | 149 | 15.49s | correct |

The compressed runs reduced slot 49 input by about 68%. The model selected
the same exact row in all compressed runs. Both Korean
`2026년 8월 27일 06시` and ISO `2026-08-27T06:00:00` model outputs now resolve
to the exact cited source value.

## Scope check

With the current sealed 64 candidate pools and table facts, slot 49 is the
only requirement routed to the table branch. Therefore this compression
does not change the prompts of the other 63 slots.

## Separate slot 9 observation

Slot 9 returned `unsupported` in two later new generations. This is not a
table-compression regression because slot 9 uses the unchanged non-table
typed evidence-ref prompt. It is a separate Qwen3 8B evidence-selection
stability issue and must not be counted as evidence for or against the
table-only compression.

## Verification

- Focused tests: 17 passed
- V3 tests: 515 passed
- Legacy tests: 72 passed
- `git diff --check`: passed
- Slot 49 generation errors: 0
- Slot 49 false-full: 0
- Slot 49 citation coordinate recovery: exact

## Decision

GO for the table-only prompt-compression diagnostic scope. Do not report a
new sealed 64 score. Slot 9 remains a separate unresolved non-table model
stability case.
