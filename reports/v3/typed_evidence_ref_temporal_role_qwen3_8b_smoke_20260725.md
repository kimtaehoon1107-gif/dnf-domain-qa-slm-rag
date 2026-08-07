# Typed evidence-ref temporal-role Qwen3 8B smoke

## Scope

- Model: `qwen3-8b:ctx8192`
- New model calls: 7 primary calls + 1 isolated retry
- Retrieval: not rerun
- Candidate pools: reused from the sealed 64-question run
- Evaluation role: targeted adaptive generation smoke, not a new generalization score
- Representative roles:
  - `effective_at`: slots 1, 9, 14
  - `event_period`: slot 17
  - `revision_cutoff`: slot 22
  - `deletion_at`: slot 49
  - `sale_period`: slot 57

## Primary run

| Slot | Previous result | New result | Transition | Notes |
|---:|---|---|---|---|
| 1 | correct | correct | preserved correct | `2026-05-28`, `E9` |
| 9 | error | correct | recovered | old `2026-06-02`/title-only evidence → new `2026-06-04`, `E7` + `E24` |
| 14 | correct | correct | preserved correct | `2026-04-23`, `E7` |
| 17 | correct | correct | preserved correct | `2026-06-04/2026-08-27`, `E26` |
| 22 | correct | correct | preserved correct | `2026-05-28`, `E4` |
| 49 | correct | no response | new regression | generation failed at the 4,000 completion-token limit |
| 57 | correct | correct | preserved correct | `2026-06-25/2026-07-30`, `E5` |

Primary-run result:

- Correct: `6/7`
- Previous error recovered: slot 9
- Previous errors still failing: none
- Previous correct cases preserved: slots 1, 14, 17, 22, 57
- New regression: slot 49
- False-full: 0

## Slot 49 isolated retry

The retry failed again, but with a different generation failure:

- Primary run: structured-output parsing failed after reaching the 4,000 completion-token limit.
- Retry: the model returned eight invented requirement IDs (`R1` to `R8`) instead of the fixed single requirement `deletion_at`.
- The batch protocol validator rejected the response with `batched requirement IDs differ from fixed requirements`.

This is not a temporal-role selection error or verifier overreject. It is a Qwen3 8B structured-output stability failure for this input. Both failures were safely converted to `abstain`; no unsupported answer was exposed.

## Interpretation

The new temporal-role prompt and evidence connection fixed the previously observed slot 9 semantic error in a real Qwen generation call:

- Old output: `2026-06-02`, citing only the update title.
- New output: `2026-06-04`, citing evidence that contains the update application date.

The change did not regress five other representative temporal-role cases. However, slot 49 shows that the pipeline still has a separate model-protocol reliability problem. This targeted smoke cannot change the official sealed `37/64` result and should not be reported as a new generalization score.
