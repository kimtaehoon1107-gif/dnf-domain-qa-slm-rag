# Partial Decomposition Controlled Arm Results

## Verdict

The reviewed Partial decomposition arm is **not promoted**. It improves grounded
Partial completion, but it also changes wholly unsupported questions into
`partial`, regresses explicit abstention, and produces two unsafe answers on the
domain safety slice. Gradio remains on `outputs/slm_lora_qwen_domain_v3_3`, and
the frozen blind set remains unqueried.

## Controlled Data And Training

- Human review: `5 approve / 18 rewrite / 1 reject`; only 23 accepted rows were
  frozen for training.
- Train QA: baseline 408 rows plus 23 reviewed rows, total 431.
- RAFT: all 408 checkpoint-250 baseline rows are byte-identical; only the 23
  reviewed rows were appended.
- Gate-balanced RAFT: 599 rows (`true=277 / partial=115 / false=207`). The new
  `partial_decomposition_train` rows remain at 1x.
- Gold positions: `1=126 / 2=134 / 3=132`; maximum share `0.3418`.
- Train/eval/blind parent, chunk, question, and every RAFT-context overlap: `0`.
- Training: Qwen2.5-0.5B-Instruct, two epochs, 276 steps, `549 train / 34 dev`,
  parent split overlap `0`, skipped rows `0`, final dev loss `0.1571`.

## Four-Dev Comparison

All generation runs use deterministic seed 42, legacy instruction, chunk-only
context, BGE-M3 hybrid retrieval, `top_k=3`, `candidate_k=100`, and a 900-character
context window.

| dev set | metric | checkpoint-250 | decomposition arm | delta |
|---|---|---:|---:|---:|
| domain | exact citation | 33/90 | 30/90 | -3 |
| domain | partial joint | 1/10 | 2/10 | +1 |
| domain | false joint | 30/30 | 21/30 | -9 |
| domain | unsafe safety rows | 0/9 | 2/9 | +2 |
| official | exact citation | 10/24 | 10/24 | 0 |
| official | false joint | 6/6 | 6/6 | 0 |
| fresh_dev | exact citation | 11/22 | 15/22 | +4 |
| fresh_dev | partial joint | 0/6 | 2/6 | +2 |
| fresh_dev | false joint | 7/8 | 5/8 | -2 |
| human Partial | exact citation | 10/20 | 10/20 | 0 |
| human Partial | partial joint | 6/20 | 7/20 | +1 |
| human Partial | evidence token recall | 0.2058 | 0.3358 | +0.1300 |

The official configuration is now identical to the baseline. One official row
has a different third-ranked non-gold chunk across retrieval runs while keeping
the same gold hit and aggregate retrieval score, so the strict row-identity gate
remains false. Promotion already fails independently on citation, false, safety,
and unsupported-abstention gates.

## Requirement-Level Result

| human Partial requirement metric | checkpoint-250 | decomposition arm | delta |
|---|---:|---:|---:|
| grounded slots answered | 6/31 | 9/31 | +3 |
| grounded slots answered and cited | 5/31 | 7/31 | +2 |
| grounded slots over-refused | 23/31 | 20/31 | -3 |
| unsupported slots explicitly abstained | 14/21 | 9/21 | -5 |
| unsupported slots over-answered | 1/21 | 0/21 | -1 |
| unsupported slots omitted | 6/21 | 12/21 | +6 |
| strict requirement joint | 2/20 | 4/20 | +2 |

The arm answers more grounded slots and recovers two strict-joint rows, but it
often drops the targeted abstention clause. This is not a clean Partial win.

## Failure Diagnosis

The intervention added 23 Partial rows and changed no existing QA or RAFT row.
Most accepted targets contain the same semantic structure: answer one supported
fact, then decline a personalized decision. On wholly unsupported questions,
the trained model now treats any retrieved DNF sentence as the supported half
and emits `partial` with an irrelevant citation.

This pattern accounts for nine domain false regressions and three fresh-dev
false regressions. Examples include account-status checks, future class ranking,
Bitcoin prediction, and weather. The domain safety regressions are prompt-attack
questions that received irrelevant DNF content plus a partial refusal.

The next experiment must therefore distinguish **mixed evidence** from
**wholly unsupported with distracting context**. Adding more generic Partial
rows or completing another full training run without that contrast is not
justified.

## Decision

- Do not promote the adapter.
- Do not change Gradio defaults.
- Do not query the frozen blind set.
- Do not weaken the predeclared gates after seeing the result.
- Before another training run, audit the false regressions and unsupported
  omissions, then design a small human-reviewed contrast set pairing Partial
  examples with unsupported-only questions under similarly tempting context.

Authoritative machine-readable result:
`reports/partial_decomposition_arm_comparison.json`.
