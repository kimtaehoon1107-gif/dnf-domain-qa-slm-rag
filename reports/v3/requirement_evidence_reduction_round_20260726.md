# Requirement-aware evidence reduction round — 2026-07-26

## Evaluation role

This is an adaptive diagnostic over already inspected generalization-64 cases.
It does not replace the sealed one-shot result (`37/64`) and is not a new
generalization score.

## Root cause

Slot 41 already had the current account-policy document at candidate rank 1.
The prompt builder expanded five chunks into 172 evidence units, including 53
historical effective dates and unrelated policy sections. The native Ollama
request was 15,936 characters and was rejected by the 12,000-character
fail-closed budget.

Slots 8 and 41 were also labeled retrieval misses by exact frozen-gold chunk
membership even though their candidate pools contained direct official
equivalent evidence:

- Slot 8: another official notice states the same Seria shop location.
- Slot 41: the current policy header states `시행일자 / 2026년 03월 15일`.

They should be recorded as acceptable-evidence omissions, not new retrieval
failures. The sealed artifact remains unchanged.

## Implementation

- Keep exact source coordinates and evidence refs.
- When a non-table prompt is large, score units using only public requirement
  fields:
  - requested temporal role,
  - relation anchors,
  - subject/surface match,
  - requested value shape,
  - question-token overlap.
- Keep heading context and adjacent label/value units.
- Keep multiple candidates only when their best unit has comparable relevance.
- Exclude weak duplicate candidate units from the model-visible prompt.
- Add deterministic `normalized_dates` for month/day evidence using the fixed
  `as_of` year. The original evidence text remains the verifier authority.
- Preserve fail-closed request and output limits.

No required value or acceptable gold evidence is used by the selector.

## Static 64-case prompt audit

The stored candidate pools were reused. No retrieval or generation was run for
this audit.

| Metric | Result |
|---|---:|
| Non-table model calls | 63 |
| Calls with reduced evidence | 51 |
| Requests over 12,000 characters | 0 |
| Maximum request | 7,627 characters |
| p50 request | 4,584 characters |
| p95 request | 6,261 characters |

Key cases:

| Slot | Evidence units | Request characters |
|---|---:|---:|
| 41 | 172 → 15 | 15,936 → 3,324 |
| 57 | 218 → 4 | 2,478 final |

## Qwen3 8B generation diagnostics

Model: `qwen3-8b:ctx8192`, native Ollama, `think=false`,
`num_predict=512`.

### Slot 41 final

- Answer: `2026년 3월 15일`
- Evidence: E3, exact source coordinates
- Input: 1,128 tokens
- Output: 68 tokens
- Latency: 4.22 seconds
- Generation error: 0

### Slot 57 corrective iteration

The first reduced prompt still exposed equivalent date ranges from four sibling
documents. Qwen selected all of them and the verifier correctly rejected the
non-colocated relation/value group. After weak duplicate candidates were
removed, Qwen initially expanded `06.25 ~ 07.30` to the calendar month. Adding
deterministic normalized dates resolved the ambiguity.

Final:

- Answer: `2026년 6월 25일 ~ 2026년 7월 30일`
- Evidence: E5 only
- Input: 684 tokens
- Output: 80 tokens
- Latency: 4.38 seconds
- Generation error: 0

The failed intermediate diagnostics are preserved and are not promotion
results.

### Regression sample

Final-code model runs covered slots:

`8, 19, 21, 27, 37, 40, 41, 46, 52, 57, 61, 62, 63`

- No confirmed semantic regression.
- No new actual false-full.
- No generation error in the valid model runs.
- Slot 40 remains content-correct against an official FAQ but is rejected by
  the narrow automatic gold.
- Slot 62 safely abstains when replaying the old wrong-month candidate pool.
- Slot 63 exposes the supported July price and keeps the unsupported August
  item hidden.

## Tests

- Focused typed-evidence tests: 30 passed, 7 subtests passed.
- Full v3 tests: 698 passed, 54 subtests passed.
- Legacy tests: 72 passed.
- `git diff --check`: passed.

## Decision

- Requirement-aware prompt reduction: diagnostic GO.
- Production/generalization promotion: still NO-GO until an untouched
  evaluation set validates the combined router, generator, and verifier.
- Do not add another search rule for slots 8 or 41. Add their equivalent
  official evidence only through a reviewed evaluation addendum.
