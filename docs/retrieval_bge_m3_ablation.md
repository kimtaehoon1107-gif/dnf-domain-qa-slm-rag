# BGE-M3 Retrieval Ablation

## Purpose

This pass tests whether the low official chunk retrieval score was partly caused by the MiniLM embedding limit and by the lexical-first reranker.

The canonical indexes were rebuilt with `BAAI/bge-m3`, while MiniLM ablation indexes were kept separately:

| Corpus | Canonical BGE-M3 index | MiniLM ablation index |
|---|---|---|
| synthetic docs | `outputs/chroma` | `outputs/chroma_minilm` |
| official chunks | `outputs/chroma_official_chunks` | `outputs/chroma_official_chunks_minilm` |
| official parent docs | `outputs/chroma_official` | not used in ablation |
| guide chunks | `outputs/chroma_guide_chunks` | not used in ablation |

Default retrieval is now:

- embedding model: `BAAI/bge-m3`
- rank mode: `hybrid`

`hybrid` is a simple normalized blend of lexical overlap and semantic distance. It is not meant to be the final reranking method; it is a controlled baseline that prevents lexical-only ordering from hiding dense retrieval gains.

## Official Chunk Eval

Eval set: `data/processed/official_eval_set.jsonl`

Answerable rows: 24

| Model | Rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| MiniLM | lexical_first | 0.0417 | 0.2083 | 0.4583 | 0.1646 |
| MiniLM | semantic | 0.0833 | 0.0833 | 0.0833 | 0.0833 |
| MiniLM | hybrid | 0.1250 | 0.2500 | 0.3333 | 0.1972 |
| BGE-M3 | lexical_first | 0.1250 | 0.5417 | 0.6250 | 0.3264 |
| BGE-M3 | semantic | 0.1250 | 0.2500 | 0.3333 | 0.1972 |
| BGE-M3 | hybrid | 0.2083 | 0.6667 | 0.7083 | 0.4063 |

Interpretation:

- BGE-M3 materially improves official chunk retrieval under the same eval set.
- Lexical-first was not purely bad; with BGE-M3 it improves hit@5 substantially over semantic-only ranking.
- The best current setting is BGE-M3 + hybrid.
- hit@1 is still low, so this does not close retrieval quality. It only gives a fairer baseline for the next chunking/reranking pass.

## Synthetic Eval

Eval set: `data/processed/eval_set.jsonl`

Answerable rows: 28

| Model | Rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| MiniLM | lexical_first | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| MiniLM | semantic | 0.7143 | 0.9286 | 0.9286 | 0.8155 |
| MiniLM | hybrid | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| BGE-M3 | lexical_first | 0.9643 | 1.0000 | 1.0000 | 0.9821 |
| BGE-M3 | semantic | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| BGE-M3 | hybrid | 0.9643 | 1.0000 | 1.0000 | 0.9821 |

Interpretation:

- The synthetic eval remains saturated, so it should not drive future retrieval decisions.
- BGE-M3 does not regress the synthetic benchmark under the selected hybrid default.

## Updated Standard Reports

The standard reports now use BGE-M3 + hybrid:

- `outputs/eval_report.json`
- `outputs/official_eval_report.json`
- `outputs/answer_eval_report.json`
- `outputs/official_answer_eval_report.json`

The full ablation outputs are saved as:

- `outputs/retrieval_ablation_official_minilm_lexical.json`
- `outputs/retrieval_ablation_official_minilm_semantic.json`
- `outputs/retrieval_ablation_official_minilm_hybrid.json`
- `outputs/retrieval_ablation_official_bge_m3_lexical.json`
- `outputs/retrieval_ablation_official_bge_m3_semantic.json`
- `outputs/retrieval_ablation_official_bge_m3_hybrid.json`
- `outputs/retrieval_ablation_synthetic_minilm_lexical.json`
- `outputs/retrieval_ablation_synthetic_minilm_semantic.json`
- `outputs/retrieval_ablation_synthetic_minilm_hybrid.json`
- `outputs/retrieval_ablation_synthetic_bge_m3_lexical.json`
- `outputs/retrieval_ablation_synthetic_bge_m3_semantic.json`
- `outputs/retrieval_ablation_synthetic_bge_m3_hybrid.json`

## Next Retrieval Work

1. Human-review the official fact questions so the eval set is less template-like.
2. Run chunk-size and section-header A/B on official chunks.
3. Try a proper sparse+dense reranker or RRF instead of the current simple hybrid score.
4. Add guide chunk eval rows before tuning guide retrieval.
