# Header-Clean + RRF Ablation

This pass first tested two retrieval-quality changes without replacing the then-canonical fixed 1200-char official chunks:

- `official_doc_chunks_no_header.jsonl`: fixed 1200-char chunks with board header/greeting/footer boilerplate removed.
- `rank_mode=rrf`: reciprocal rank fusion over semantic distance rank and lexical overlap rank.

At experiment time, the canonical `data/processed/official_doc_chunks.jsonl` and `outputs/chroma_official_chunks` were left unchanged. The no-header variant was promoted only after this A/B showed the tradeoff clearly.

## Artifacts

| Artifact | Rows | Purpose |
|---|---:|---|
| `data/processed/official_doc_chunks.jsonl` | 197 | promoted header-clean canonical chunks |
| `data/processed/official_doc_chunks_no_header.jsonl` | 197 | header-clean fixed chunks |
| `data/processed/official_eval_set.jsonl` | 30 | promoted official eval remapped to header-clean chunks |
| `data/processed/official_eval_set_no_header.jsonl` | 30 | current official eval remapped to no-header chunks |
| `outputs/chroma_official_chunks` | 197 | promoted BGE-M3 canonical index |
| `outputs/chroma_official_chunks_no_header` | 197 | BGE-M3 no-header Chroma index |

Remap quality: all 24 answerable official eval rows matched by exact evidence span.

## Boilerplate Noise

Noise was measured with the same cleanup patterns used by `prepare_chunks.py`.

| Chunk set | chunks | noisy chunks |
|---|---:|---:|
| canonical fixed 1200 | 200 | 63 |
| no-header fixed 1200 | 197 | 0 |

Answer-level boilerplate noise also dropped from 10 rows to 0 rows on the official answer eval.

## Retrieval Results

All rows use BGE-M3, top-k 5, and chunk-level expected IDs.

| Variant | rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| pre-promotion fixed 1200 | hybrid | 0.2917 | 0.6250 | 0.7083 | 0.4472 |
| pre-promotion fixed 1200 | rrf | 0.2083 | 0.4583 | 0.5000 | 0.3368 |
| no-header fixed 1200 | hybrid | 0.3333 | 0.6250 | 0.6667 | 0.4736 |
| no-header fixed 1200 | rrf | 0.3333 | 0.4583 | 0.5833 | 0.4090 |

## Row-Level Changes

The hit@5 drop is exactly one answerable row:

| Eval row | expected chunk | canonical hybrid | no-header hybrid | note |
|---|---|---|---|---|
| `official_eval_0004` | `official_update_2926972__chunk_001` | rank 5, hit | outside top 5, miss | a boundary case moved by one competing chunk |

Five other rows changed reciprocal rank without changing hit@5 status:

| Eval row | canonical reciprocal rank | no-header reciprocal rank |
|---|---:|---:|
| `official_eval_0005` | 0.5000 | 1.0000 |
| `official_eval_0014` | 1.0000 | 0.5000 |
| `official_eval_0015` | 0.5000 | 1.0000 |
| `official_eval_0016` | 0.3333 | 0.5000 |
| `official_eval_0021` | 0.3333 | 0.5000 |

This means the hit@5 loss is not a broad retrieval regression. It is one edge case at the top-5 boundary, while top-1, MRR, citation quality, answer relevance, and boilerplate removal improve.

## Answer Results

| Variant | rank mode | answerability acc | answerable citation hit | answer relevance | atomic fact support | unsupported rows |
|---|---|---:|---:|---:|---:|---:|
| pre-promotion fixed 1200 | hybrid | 1.0000 | 0.2917 | 0.3841 | 0.9926 | 2 |
| pre-promotion fixed 1200 | rrf | 1.0000 | 0.2083 | 0.4097 | 0.9926 | 2 |
| no-header fixed 1200 | hybrid | 1.0000 | 0.3333 | 0.4106 | 1.0000 | 0 |
| no-header fixed 1200 | rrf | 1.0000 | 0.3333 | 0.4780 | 1.0000 | 0 |

## Interpretation

Header cleanup is useful for answer quality: it removes board boilerplate from chunks and generated answers, improves hit@1/MRR, improves answerable citation hit, and removes unsupported fact rows in this lightweight evaluator.

RRF is not a promotion candidate yet. On this small official eval it lowers hit@3/hit@5 and MRR compared with the existing hybrid ranker. It remains useful as a transparent baseline, but the next ranking improvement should likely be a reranker A/B rather than promoting RRF.

Promotion decision: promote `no-header + hybrid` to canonical, with the row-level hit@5 tradeoff recorded above. RRF remains an ablation baseline, not a promoted ranker.

## Reproduction

```powershell
python src/prepare_chunks.py --docs data/raw/official_docs.jsonl --output data/processed/official_doc_chunks_no_header.jsonl --max-chars 1200 --overlap-chars 80 --clean-board-header
python src/remap_eval_chunks.py --eval-set data/processed/official_eval_set.jsonl --chunks data/processed/official_doc_chunks_no_header.jsonl --output data/processed/official_eval_set_no_header.jsonl
python src/build_index.py --docs data/processed/official_doc_chunks_no_header.jsonl --persist-dir outputs/chroma_official_chunks_no_header --model-name BAAI/bge-m3 --reset

python src/evaluate.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_canonical_hybrid.json
python src/evaluate.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode rrf --top-k 5 --output outputs/official_eval_canonical_rrf.json
python src/evaluate.py --eval-set data/processed/official_eval_set_no_header.jsonl --persist-dir outputs/chroma_official_chunks_no_header --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_no_header_hybrid.json
python src/evaluate.py --eval-set data/processed/official_eval_set_no_header.jsonl --persist-dir outputs/chroma_official_chunks_no_header --model-name BAAI/bge-m3 --rank-mode rrf --top-k 5 --output outputs/official_eval_no_header_rrf.json
```
