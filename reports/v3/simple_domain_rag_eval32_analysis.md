# Simple Domain RAG — fixed 32 evaluation

## Configuration

- Evaluation set: reviewed requirement-surface canary 32
- Retrieval: global BM25 + BGE-M3 hybrid top 20
- Reranker: BGE reranker top 5
- Generator: `qwen3-8b:ctx8192`
- Verification: candidate membership, exact contiguous quote, current temporal validity,
  answer numeric/date token support
- No semantic planner, extractive assembler, atomic table rows, or requirement-specific
  retrieval

## Primary results

| Metric | Result |
|---|---:|
| All gold evidence groups present in top 5 | 28/32 (87.5%) |
| All gold chunks cited | 18/32 (56.3%) |
| All gold literal spans cited | 15/32 (46.9%) |
| Literal success when candidates were present | 15/28 (53.6%) |
| Strict literal false-full | 6/32 (18.8%) |
| Exact exposed citation slices | 32/32 (100%) |
| Requirement-count match | 31/32 (96.9%) |
| Generation errors | 0 |
| Response modes | full 21 / partial 6 / abstain 5 |

The run took 978 seconds and used 139,640 input tokens and 12,648 output
tokens.

## Manual review of the six strict false-full cases

Four cases were answer-correct but failed the immutable literal-span scorer:

- Slot 11: the citation omitted only the leading list marker from the gold span.
- Slot 12: the correct long evidence was cited as multiple shorter exact slices.
- Slot 16: the citation omitted the leading `단,` from one correct sentence.
- Slot 32: the answer and exact source quote were correct, but wording and boundary
  differed from the long gold span.

Two cases were genuinely unsafe semantic false-full:

- Slot 21: a DNF account-withdrawal FAQ was used for a guild withdrawal question.
- Slot 22: general policy clauses were used instead of the requested guild
  dissolution clauses.

Therefore:

- Strict immutable score: 15/32.
- Answer-correct full responses after reviewing only the strict false-full cases:
  19/32.
- Clearly unsafe semantic full responses: 2/32.

The adjusted number is diagnostic, not a replacement for the frozen strict score.

## Retrieval misses

All four top-5 misses were the account-policy block, slots 21–24.

Gold reranker positions when the same global pool was inspected more deeply:

| Slot | Gold position |
|---|---:|
| 21 | 12 |
| 22 | 10 |
| 23 | outside retrieved top 20 |
| 24 | 9 |

Top 10 alone would recover slots 22 and 24. Top 20 would also recover slot 21,
but slot 23 needs source-aware retrieval.

## Candidate-present safe failures

Nine candidate-covered cases became partial or abstain:

- Slots 7, 8, 13, 17, 18, 20, 29: model-produced quote was not an exact contiguous
  source substring.
- Slots 5 and 31: answer numeric/date tokens were not supported by the cited quote.
- Slot 18 additionally expanded two gold requirements into three model requirements.

This shows that the current exact-quote interface is stricter than a conventional
chunk-ID citation RAG and causes substantial over-rejection.

## Segment results

| Segment | Candidate coverage | Strict literal | Strict false-full |
|---|---:|---:|---:|
| Table sources | 8/8 | 5/8 | 1/8 |
| Non-table sources | 20/24 | 10/24 | 5/24 |
| One requirement | 7/8 | 4/8 | 1/8 |
| Multiple requirements | 21/24 | 11/24 | 5/24 |

The table-source false-full was slot 32, which manual review found answer-correct.
The table path therefore produced no clearly unsafe semantic full answer in this run.

## Interpretation

Compared with the previously reported 12/22 candidate-present result:

- Retrieval coverage improved from 22/32 to 28/32.
- Overall strict success improved from 12/32 to 15/32.
- Conditional selection remained effectively unchanged:
  `12/22 = 54.5%` versus `15/28 = 53.6%`.

The simpler pipeline improved the number of questions that reach the generator, but
did not improve Qwen3:8b's conditional evidence-selection rate.

The next minimal A/B should keep retrieval results fixed and compare:

1. Current exact-quote output contract.
2. Answer + short candidate reference only, with chunk-level numeric/date support
   verification.

Separately, account-policy questions need a small source-aware candidate pool or
union; globally increasing context depth is insufficient for slot 23.
