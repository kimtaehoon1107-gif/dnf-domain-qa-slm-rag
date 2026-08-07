# Generalization-64 relation-group boolean / currency-unit diagnostic

## Scope

This is a post-hoc verifier-only replay. It reuses the sealed 64 questions,
stored candidates, and stored Qwen3 8B outputs. It does not replace the official
sealed result.

```text
official sealed result: 37/64
new model calls: 0
retrieval reruns: 0
```

## Changes

1. Boolean evidence is split into adjacent groups within the same chunk.
2. Only groups matching the requirement subject and relation can support or
   contradict the boolean value.
3. Citations from unrelated boolean groups are removed from the exposed answer.
4. A relation-compatible contradiction still fails closed.
5. Amount-only `price` and `currency` values inherit a unit only when the
   selected evidence has exactly one matching `(amount, unit)` pair.
6. An explicit model-supplied currency unit must match the evidence unit.

## Diagnostic result

```text
gold-value complete: 37/64 -> 43/64 (+6)
correct / incorrect / no-response: 43 / 4 / 17
verifier overreject: 14 -> 8
automatic false-full flag: 1 -> 1
regressions: 0
```

Recovered slots:

```text
12, 15, 35, 52, 54, 58
```

Slot 38 remains correct. Its answer now cites only the relation-compatible
evidence stating that existing Goblin Pad users can reissue it; unrelated
negative evidence about issuance after disposal is removed.

## Slot 47 adjudication warning

The remaining automatic false-full flag is not safe to call a real semantic
false-full without re-adjudication. The frozen gold marks `processing_days` as
unsupported, but the selected official FAQ evidence says:

```text
이용제한 재조사를 위해 1:1문의를 접수한 경우
유형에 따라 3~5일 정도 소요될 수 있는 점 참고 부탁드립니다.
```

Source:

```text
[게임이용제한] 이용 제한 해제를 어떻게 하나요?
https://df.nexon.com/customer/faq?faq_no=4860
```

The evidence directly connects an account-restriction reinvestigation request
to a 3–5 day processing period. The sealed label must remain unchanged, but the
case should be human re-adjudicated before using it as a false-full example.

## Verification

```text
24 tests passed, 7 subtests passed
python compile checks passed
git diff --check passed
```

Artifacts:

```text
reports/v3/typed_evidence_ref_generalization_64_relation_group_currency_v2.json
outputs/v3/diagnostics/typed_evidence_ref_generalization_64_relation_group_currency_v2.jsonl
```
