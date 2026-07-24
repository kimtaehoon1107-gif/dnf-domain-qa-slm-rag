# Latest Typed pipeline Qwen3 8B full-64 adaptive diagnostic

## Scope

This run evaluates the current temporal-role prompt, relation-group/currency
verifier, table row-subject binding, and table-only prompt compression
together.

```text
model: qwen3-8b:ctx8192
questions: 64
new model calls: 64
retrieval reruns: 0
stored candidate pools reused: yes
evaluation role: adaptive diagnostic, not a new sealed score
```

The official sealed one-shot result remains `37/64`. The prior `43/64` result
is a verifier-only replay of the original stored Qwen outputs. This report is
a new-generation diagnostic of the latest pipeline and does not replace
either record.

## Result

| Metric | Official one-shot | Verifier-only v2 | Latest new generation |
|---|---:|---:|---:|
| Gold-value complete | 37/64 | 43/64 | **45/64** |
| Approved direct evidence hit | 31/64 | **37/64** | 35/64 |
| Candidate gold covered | 54/64 | 54/64 | 54/64 |
| Verifier overreject | 14 | 8 | **5** |
| Generation errors | 3 | 3 | 3 |
| Automatic frozen-gold false-full flags | 1 | 1 | **3** |
| Mean latency | 24.20s | replayed | **15.76s** |
| p50 latency | 21.23s | replayed | **13.67s** |
| p95 latency | 44.67s | replayed | **37.20s** |
| Input tokens | 268,535 | replayed | 290,954 |
| Total tokens | 273,998 | replayed | 297,176 |

Latest outcomes:

```text
correct: 45
incorrect: 4
no_response: 15
```

## Movement versus verifier-only v2

```text
wins:   9, 10, 39, 53, 55, 61
losses: 12, 41, 43, 63
net:    +2
```

Approved direct-evidence movement:

```text
wins:   9, 10, 39, 53, 55
losses: 12, 20, 22, 43, 45, 58, 63
net:    -2
```

The headline value score improved, but direct approved evidence and
case-level stability regressed.

## Targeted changes

### Slot 9

```text
question:
시즌 11 Act 2 '제국의 파도 & 폭권' 업데이트는 언제 적용됐어?

answer:
2026년 6월 4일

evidence refs:
E7, E24

result:
correct, direct evidence hit, false-full 0
```

The full run reproduced the intended temporal-role recovery. Earlier targeted
retries also produced `unsupported`, so the Qwen selection remains
non-deterministic even though this run succeeded.

### Slot 49

```text
question:
프리미엄 코인샵의 트로피컬 바캉스 무기 아바타 상자는 언제 삭제돼?

answer:
2026년 8월 27일 06시

input tokens:
2,578

latency:
15.65s

result:
correct, exact table-row citation, false-full 0
```

The row-subject binding and table-only compression remained correct in the
full run.

## Regressions and instability

Compared with verifier-only v2:

- Slot 12: the model changed the value type and the verifier safely rejected
  both requirements.
- Slot 41: generation/protocol error.
- Slot 43: the model selected the same exception evidence for both the general
  rule and exception requirements.
- Slot 63: the model answered an unsupported August item name from an
  unrelated Seria Shop package.

Generation errors moved between runs rather than disappearing:

```text
latest generation-error slots: 21, 40, 41
```

This is evidence of Qwen3 8B structured-output and evidence-selection
instability, not a deterministic verifier regression.

## False-full re-adjudication

Automatic flags:

```text
31, 47, 63
```

- Slot 31 remains a frozen-gold acceptable-evidence omission candidate; the
  official source supports the `10개` preset limit.
- Slot 47 remains a frozen-gold acceptable-evidence omission candidate; the
  official FAQ directly links reinvestigation contact to `3~5일`.
- Slot 63 is an actual semantic false-full in this run. The frozen requirement
  asks for the unsupported August monthly-item name, but the model exposed
  `트로피컬 바캉스 패키지` from an unrelated Seria Shop document.

Therefore:

```text
automatic frozen-gold flags: 3
source-reviewed actual false-full: 1 (slot 63)
```

## Verdict

```text
slot 49 table binding/compression: GO
slot 9 temporal-role mechanism: diagnostic success, generation stability unresolved
latest full-64 pipeline promotion: NO-GO
```

The latest pipeline obtains the best adaptive value score so far (`45/64`),
but it has four regressions against verifier-only v2, direct-evidence recall
falls to `35/64`, generation errors remain at three, and one real false-full
appears. Do not promote it as a production or generalization result.

Do not add more slot-specific rules to this 64-question set. A future
promotion attempt must freeze this code and evaluate it on a new untouched,
human-reviewed set.

## Artifacts

```text
cases:
outputs/v3/diagnostics/typed_evidence_ref_latest_pipeline_qwen3_8b_full64_20260725.jsonl
sha256:
da70ebc794bb341f9de48733c8b5f1282c4877235ae318cdb86ff77d1978b5d5

summary:
reports/v3/typed_evidence_ref_latest_pipeline_qwen3_8b_full64_20260725.json
sha256:
5324a247e528a4f7e416b908861344250110d991a9759dc96ff83c5fe26e5d9f
```
