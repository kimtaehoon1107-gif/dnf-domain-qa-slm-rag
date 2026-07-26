# Policy/month binding Qwen3 8B adaptive full-64 regression

Date: 2026-07-27

## Evaluation role

This is an adaptive full-64 regression result over an already inspected set.
It is not a new generalization score and does not replace the official sealed
one-shot result of `37/64`.

Retrieval was not re-executed. The run reused the stored Product Router
candidate pools with source SHA-256:

```text
515ca70fa0893898faafd189493a0a0c61bbbfa8a35b9e8444681ee10d31ab69
```

Model and generation protocol:

```text
qwen3-8b:ctx8192
one same-schema batch call per question
Typed value + evidence_ref
native Ollama for non-table calls
think=false
num_ctx=8192
num_predict=512
semantic fallback disabled
```

The first foreground runner was terminated by the orchestration timeout before
it wrote progress or result artifacts. It may have issued one incomplete
slot-1 request. The completed artifact records exactly 64 successful calls and
is the only run used for scoring.

## Headline comparison

| Metric | Previous Product Router | Policy/month binding |
|---|---:|---:|
| Typed-value complete | 50/64 | **55/64** |
| Approved frozen evidence | 44/64 | **50/64** |
| Strict candidate coverage | 62/64 | **62/64** |
| Generation errors | 0 | **0** |
| Citation coordinates exact | yes | **yes** |
| Mean latency | 9.07s | **5.69s** |
| p50 latency | 8.08s | **5.31s** |
| p95 latency | 13.64s | **7.65s** |
| Input tokens | 127,429 | **121,864** |
| Output tokens | 5,769 | **5,716** |

Latency changed by `-37.3%` mean, `-34.3%` p50, and `-43.9%` p95.
Input tokens changed by `-4.4%`.

The separate reviewed equivalent-evidence addendum recognizes official
equivalent evidence for slots 8 and 41. Counting that addendum separately
would interpret direct evidence as `52/64`; the frozen automatic metric remains
`50/64`.

## Row-level transitions

| Transition | Slots |
|---|---|
| Recovered | `1, 6, 60, 61, 62, 63` |
| Preserved correct | 49 slots |
| Persistent error | `2, 5, 12, 20, 30, 34, 47, 51` |
| New regression | **`25`** |

The score arithmetic is:

```text
50 previous correct
+ 6 recovered
- 1 regressed
= 55/64
```

The only correctness change outside the intended policy/month group is slot
25.

## Slot 25 regression

Question:

```text
던파ON 출석체크는 매일 몇 시에 갱신되고,
보상 교환의 1주 기준은 언제야?
```

The model output was unchanged from the previous correct run:

```json
{
  "daily_reset_time": {
    "value": "06:00",
    "evidence_refs": ["E3", "E18"]
  },
  "weekly_reset_at": {
    "value": "매주 목요일 오전 6시",
    "evidence_refs": ["E7"]
  }
}
```

E3 directly states:

```text
출석체크는 매일 06시를 기준으로 갱신됩니다.
```

The tightened enum evidence check did not normalize `06:00` and `06시` as the
same time. It rejected the first requirement with:

```text
typed_value_not_supported_by_evidence
subject_relation_value_not_colocated
```

This is a real product-output regression from `full_answer` to
`partial_answer`. It is a safe overreject rather than a newly exposed wrong
claim, but it violates the predeclared zero-regression gate. No slot-specific
repair was added after observing this result.

## Safety interpretation

The automatic frozen-gold unsupported false-full flag remains slot 31.
The reviewed addendum contains direct official evidence that avatar presets
can be expanded to a maximum of ten, so:

```text
automatic frozen-gold unsupported false-full: 1
source-reviewed unsupported false-full:       0
new unsupported false-full versus baseline:   0
```

This narrow metric does not mean every full response is correct. Two
pre-existing incorrect full responses remain:

- Slot 30 returns only level 115 and omits level 110.
- Slot 51 returns `15 골드 코인` instead of the clone-top price
  `2,600 세라`.

Therefore a broader semantic definition of false-full yields `2` existing
incorrect full responses. Neither was newly introduced by this round.

## Remaining failures

```text
Verifier overreject:
2, 5, 25, 34

Incomplete or wrong generator selection:
12, 20, 30, 47, 51

Frozen-gold unsupported flag with reviewed official support:
31
```

Automatic outcomes:

```text
correct:     55
incorrect:    6
no_response:  3
```

## Protocol verification

- Result rows: `64`
- Recorded model calls: `64`
- Generation/protocol errors: `0`
- Non-empty hidden reasoning: `0`
- Maximum actual output: `232` tokens
- Exact citation coordinate restoration: `100%`
- Full repository tests: `789 passed`, `54 subtests passed`
- `git diff --check`: passed before execution

Artifact SHA-256:

```text
cases:
782e1ed25e23a79e3cc2c106363c6752985e0e572e30f60b3c771a4aef0e798f

JSON summary:
fe04ecfffe6cfc4cf1e24297cd03ea199551fce0d1ea1dfe9942ab770fad81ec
```

## Verdict

```text
Score >= 50/64:                  PASS
Target near 55/64:               PASS
Generation errors = 0:           PASS
New unsupported false-full = 0:  PASS
Exact citation coordinates:      PASS
Existing semantic regression = 0: FAIL (slot 25)
No unrelated correctness change: FAIL (slot 25)
```

Overall verdict: **NO-GO for promotion**.

The `55/64` result is the best observed adaptive value-completeness result, but
it cannot be promoted because the predeclared zero-regression condition failed.
Do not add another slot-specific rule to this 64-question set, do not enable
semantic fallback, and do not replace the official `37/64` result. Preserve
this run as an adaptive regression artifact and move the next decision to an
untouched evaluation set.
