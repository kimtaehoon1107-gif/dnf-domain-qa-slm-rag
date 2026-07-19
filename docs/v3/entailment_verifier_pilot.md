# DNF RAG v3 Controlled Entailment Verifier Pilot

## Scope

This cycle measures only whether a local NLI model can distinguish `support`,
`contradiction`, and `insufficient` on a small controlled set. It does not run a
Generator, Router, training job, or frozen blind evaluation.

## Case contract

The builder selects the lexicographically first eligible single-fact retrieval-dev
row for each of the eight official source IDs. Every selected official evidence
span produces three cases:

- `support`: the reviewed dev gold answer is used as the claim.
- `contradiction`: exactly one documented value or polarity is changed in that
  answer (for example, `2026년 7월 30일` to `2026년 7월 31일`).
- `insufficient`: the next source's gold answer is paired with the current source's
  evidence in a fixed cyclic order.

The 24 labels are agent-constructed controls. They are never training data, are not
eligible for the final benchmark, and must not be reported as natural-distribution
accuracy. A human-reviewed natural claim set is the next required evaluation input.

## Model contract

The premise is `evidence_text` and the hypothesis is `claim_text`. NLI entailment,
contradiction, and neutral map to `support`, `contradiction`, and `insufficient`.
The scorer does not pass gold labels to either model.

The fixed candidates are:

- [MoritzLaurer/mDeBERTa-v3-base-mnli-xnli](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli), revision `8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c`.
- [Huffon/klue-roberta-base-nli](https://huggingface.co/Huffon/klue-roberta-base-nli), revision `3778d23ecb30a63babb17f5efb37b1493b08d975`.

KLUE-RoBERTa declares `type_vocab_size=1`, while its legacy BERT tokenizer emits
segment ID 1 for the second sentence. The scorer therefore relies on the pair
separator tokens and omits `token_type_ids` for both fixed models.

## Gates

A controlled development candidate needs overall accuracy of at least `0.80` and
recall of at least `0.75` for every label. Production remains blocked regardless of
this pilot until all of the following exist:

- human-reviewed natural support/contradiction/insufficient claims;
- an independent holdout and confidence calibration;
- runtime integration tests and online latency measurements.

The content-addressed report in `reports/v3` is the authoritative result and
contains the exact input, model-file, score, and report hashes.
