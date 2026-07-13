# Phase C Deterministic Contextual Prefix A/B

## Verdict

The deterministic contextual-prefix index is **rejected**. It did not pass the cross-set retrieval no-regression gate, so generation A/B was not run.

The experimental artifact preserved all 1,307 chunk IDs and used a separate BGE-M3 index. `build_index.py` already prepends the title in both arms, so the added prefix contained only stable available metadata: document type, published date, effective period, and section. Collection timestamps, URLs, and document numbers were excluded.

## Retrieval Results

All rows were evaluated with `hybrid`, `candidate_k=100`, and one top-10 retrieval pass after model warm-up.

| set | arm | hit@1 | hit@3 | hit@5 | hit@10 | MRR@10 | query latency |
|---|---|---:|---:|---:|---:|---:|---:|
| domain | canonical | 0.3000 | 0.5222 | 0.5889 | 0.6556 | 0.4239 | 0.0631s |
| domain | contextual | 0.2667 | 0.4556 | 0.5111 | 0.6222 | 0.3754 | 0.0637s |
| official | canonical | 0.2083 | 0.5000 | 0.5000 | 0.6667 | 0.3615 | 0.0660s |
| official | contextual | 0.2500 | 0.4167 | 0.5000 | 0.5833 | 0.3637 | 0.0672s |
| fresh_dev | canonical | 0.7727 | 0.9545 | 0.9545 | 1.0000 | 0.8687 | 0.0681s |
| fresh_dev | contextual | 0.7727 | 0.9545 | 0.9545 | 1.0000 | 0.8687 | 0.0668s |
| human partial | canonical | 0.7000 | 0.9000 | 0.9500 | 0.9500 | 0.8017 | 0.0901s |
| human partial | contextual | 0.7000 | 0.8500 | 0.9000 | 0.9500 | 0.7931 | 0.0729s |

## Row-Level Check

The regression is not an aggregate-only artifact:

- domain: `7` improved ranks, `18` worse ranks, `65` ties; one missing gold was rescued but four became newly missing in top-10;
- official: `4` improved, `7` worse, `13` ties; two gold chunks became newly missing;
- fresh_dev: `1` improved, `1` worse, `20` ties;
- human partial: `0` improved, `2` worse, `18` ties.

The prefix mostly adds repeated category/date/section tokens to already title-prefixed chunks. On these corpora that signal does not improve candidate ordering consistently and sometimes dilutes the body facts used by the queries. Query latency is effectively unchanged; retrieval quality, not cost, is the rejection reason.

## Decision

- Keep canonical `BGE-M3 + hybrid + chunk-only` retrieval.
- Do not enable the contextual index in Gradio.
- Do not run generation A/B after the retrieval gate failed.
- Do not proceed to selective LLM contextual retrieval: neither the sibling-window nor deterministic-prefix experiment justified the added complexity.
- Frozen blind remains untouched.

The next step is not another context variant. The retrieval/context configuration is frozen for this cycle; the next clean SLM run requires a specific train-side intervention supported by the existing partial/citation failure diagnosis, rather than repeating the rejected checkpoint-250 recipe.
