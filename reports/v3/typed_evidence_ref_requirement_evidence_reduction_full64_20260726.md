# Typed evidence-ref requirement evidence reduction full-64 diagnostic

## Evaluation role

This is an adaptive regression diagnostic over the already inspected 64-case
set. It reuses the stored candidate pools and performs 64 new Qwen3 8B calls.
It does not replace the official sealed one-shot result (`37/64`).

```text
model: qwen3-8b:ctx8192
generation protocol: native Ollama, think=false, num_ctx=8192, num_predict=512
retrieval rerun: no
stored candidate pools reused: yes
new model calls: 64
```

## Result

| Metric | Previous adaptive full-64 | Evidence-reduced full-64 |
|---|---:|---:|
| Gold-value complete | 45/64 | **44/64** |
| Approved direct evidence | 35/64 | **34/64** |
| Generation errors | 3 | **0** |
| Automatic frozen-gold false-full flags | 3 | **1** |
| Source-reviewed actual false-full | 1 | **0** |
| Mean latency | 15.76s | **5.41s** |
| p50 latency | 13.67s | **4.96s** |
| p95 latency | 37.20s | **6.88s** |
| Input tokens | 290,954 | **111,191** |
| Total tokens | 297,176 | **116,794** |

Current automatic outcomes:

```text
correct: 44
incorrect: 9
no_response: 11
all citation slices exact: true
schema errors: 0
hidden reasoning outputs: 0
```

The input-token reduction is `61.8%`. Mean latency fell `65.7%`, and p95
latency fell `81.5%`. The maximum output was 232 tokens; the prior
4,000-token hidden-reasoning failure did not recur.

For the 63 non-table calls:

```text
mean request characters: 4,344
p50 request characters: 4,584
p95 request characters: 7,406
maximum request characters: 7,627
requests over 12,000 characters: 0
```

## Movement versus the previous adaptive generation

```text
wins:   21, 40, 41, 63
losses: 4, 20, 25, 35, 38
net:    -1
```

Important recoveries:

- Slot 21 returned both `40%` attack amplification and `10%` buff
  amplification with the exact option row.
- Slot 40 completed without hidden reasoning or a generation error and cited
  the official coupon-use instructions.
- Slot 41 returned `2026-03-15` from the current policy header with 1,128 input
  tokens and 4.31s latency.
- Slot 63 returned the supported July price and kept the unsupported August
  item name hidden.

## Regression review

The full run exposed a general flaw in the current evidence reducer: it scores
the batch globally, so evidence for the first requirement can consume the
selection budget while evidence needed only by a sibling requirement is
removed.

- Slot 4: both exact body units for the ISP impact and permission action were
  removed; only the notice title and metadata remained visible.
- Slot 25: the daily reset evidence remained, but the weekly-reset evidence
  was removed.
- Slot 38: the issue-stop date remained, while the positive existing-user
  reissue sentence was removed and a nearby negative disposal sentence
  remained.
- Slot 20: the date and a compact line containing both channel names remained,
  but the second approved channel sentence was removed and Qwen abstained on
  the channel requirement. This is a mixed reduction/model-selection failure.
- Slot 35: both same-account and other-account relation lines remained visible,
  but Qwen cited only the relation line without the conclusion value. The
  verifier correctly blocked it; this is evidence-ref selection instability,
  not a verifier failure.

Slot 43 was already incorrect in the previous adaptive run. The current
reducer also omitted the second exception (`불특정 다수의 고객에게 피해`),
confirming the same sibling-requirement coverage problem.

## False-full adjudication

The automatic false-full flag is slot 31:

```text
question: avatar part count and preset limit
answer: 11 parts, preset limit 10
evidence: official Seria Shop row states that presets can expand to 10
```

The frozen gold marks the preset limit unsupported, but the cited official
source directly supports the answer. It is an acceptable-evidence/gold
omission, not an actual semantic false-full.

```text
automatic frozen-gold false-full: 1 (slot 31)
source-reviewed actual false-full: 0
```

## Verdict

```text
generation protocol and prompt budget: GO
current global evidence-unit reducer: NO-GO for promotion
combined pipeline promotion: NO-GO
```

The speed and generation-stability improvements are material, but three clear
answer regressions were caused by dropping sibling-requirement evidence. The
next correction should be a general per-requirement evidence-coverage
constraint, not another slot-specific rule. Each requirement must retain at
least one high-scoring relation/value unit before the shared prompt budget is
filled.

## Artifacts

```text
cases:
outputs/v3/diagnostics/typed_evidence_ref_requirement_evidence_reduction_full64_20260726.jsonl
sha256:
3055c2e72750f99bdb8b9bcce7df69f855f60e4ec3aabaa551efffd917a40c69

summary:
reports/v3/typed_evidence_ref_requirement_evidence_reduction_full64_20260726.json
sha256:
42c6bb7118703f41a0fac44fe600996ffc662bdbd8108742e6863b51c5706618
```
