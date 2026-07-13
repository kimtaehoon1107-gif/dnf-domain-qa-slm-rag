# Partial Requirement Diagnosis

## Measurement

The frozen 20-row human Partial development set remains unchanged and evaluation-only. A separate annotation artifact decomposes it into `31 grounded` and `21 unsupported` requirement slots.

Grounded slots define required fact groups and exact chunk citations. Unsupported slots define the personal decision topic that must be explicitly mentioned and abstained from. A generic whole-answer refusal does not satisfy the unsupported slot. Row-level joint success requires:

1. predicted answerability is `partial`;
2. every grounded slot is answered;
3. every grounded slot cites an expected chunk;
4. every unsupported slot is explicitly mentioned and abstained from.

The gold-answer oracle passes `20/20`, with every slot metric at `1.0`. This proves the annotations accept the reviewed target answers before they are used to diagnose a model.

## Checkpoint-250 Result

Source: `outputs/slm_lora_answer_filtered_blind_safe_v2_parent_group/checkpoint-250` with the existing deterministic human-partial report.

| metric | result |
|---|---:|
| grounded slots answered | 6/31 (0.1935) |
| grounded slots answered and correctly cited | 5/31 (0.1613) |
| grounded slot over-refusal | 23/31 (0.7419) |
| unsupported slots explicitly abstained | 14/21 (0.6667) |
| unsupported slots over-answered | 1/21 (0.0476) |
| unsupported slots omitted | 6/21 (0.2857) |
| strict requirement joint success | 2/20 (0.1000) |

Only `partial_dev_human_0001` and `partial_dev_human_0009` pass every requirement. Failure counts by row are:

- grounded slot missing: `18/20`;
- grounded over-refusal: `17/20`;
- citation missing: `10/20`;
- unsupported request omitted: `6/20`;
- answerability predicted non-Partial: `3/20`;
- retrieval miss: `2/20`;
- unsupported request over-answered: `1/20`.

## Interpretation

The dominant failure is not lack of refusal. The model usually emits an abstention, but often copies a nearby wrong fact, answers only one of several grounded requirements, or omits the grounded request entirely. Retrieval hit is present on `18/20` rows, while strict joint success is only `2/20`; the main intervention must therefore teach decomposition and grounded-slot completion rather than add more generic false/refusal rows.

## Train-Only Candidate Gate

The first broad 80-row draft was discarded after manual inspection because low-quality source questions such as duplicated “사용 방법” templates propagated into the proposed questions. The accepted candidate-generation rule now permits only natural `casual_paraphrase_train` and `contrastive_true_train` source rows.

Current pending artifact:

- candidates: `data/processed/domain_partial_decomposition_train_candidates.jsonl`;
- human review: `data/review/partial_decomposition_train_review_24.csv`;
- rows: `24`, all included in review;
- source intents: `16 event_fact / 8 guide_fact`;
- source parents: `9`, maximum three rows per parent;
- blocked eval/blind parent, chunk, and question overlap: `0`;
- missing chunks and evidence-span mismatches: `0`;
- repeated generic refusal target: `0`.

The candidate artifact is `pending_human_review` and must not enter train/RAFT. The reviewer must confirm grounded fact correctness, unsupported-request naturalness, and targeted-abstention correctness for every row. Rejected or rewritten rows are resolved before gold-position and RAFT validation.
