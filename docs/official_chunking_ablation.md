# Official Chunking Ablation

## Purpose

This pass tests whether the remaining official retrieval failures are caused by chunk size and section handling after the BGE-M3 migration.

Baseline:

- chunks: `data/processed/official_doc_chunks.jsonl`
- index: `outputs/chroma_official_chunks`
- model: `BAAI/bge-m3`
- rank mode: `hybrid`
- chunking: fixed 1600 chars / 200 overlap

The A/B variants were first kept separate. After this result, fixed 1200-char chunks were promoted to the canonical `official_doc_chunks.jsonl` path and eval/train/RAFT were regenerated.

## Variants

| Variant | Chunks | Eval set | Index |
|---|---:|---|---|
| section 600 | 748 | `data/processed/official_eval_set_section_600.jsonl` | `outputs/chroma_official_chunks_section_600` |
| section 900 | 624 | `data/processed/official_eval_set_section_900.jsonl` | `outputs/chroma_official_chunks_section_900` |
| section 1200 | 572 | `data/processed/official_eval_set_section_1200.jsonl` | `outputs/chroma_official_chunks_section_1200` |
| fixed 600 | 389 | `data/processed/official_eval_set_fixed_600.jsonl` | `outputs/chroma_official_chunks_fixed_600` |
| fixed 900 | 260 | `data/processed/official_eval_set_fixed_900.jsonl` | `outputs/chroma_official_chunks_fixed_900` |
| fixed 1200 | 200 | `data/processed/official_eval_set_fixed_1200.jsonl` | `outputs/chroma_official_chunks_fixed_1200` |

Each variant eval set remaps `expected_chunk_id` by locating the row's `evidence_span` in the new chunk file. This avoids falsely scoring a new chunking scheme against old chunk IDs.

## Retrieval Results

All rows use BGE-M3 + `hybrid`, top-k 5.

| Variant | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| baseline 1600 | 0.2083 | 0.6667 | 0.7083 | 0.4062 |
| section 600 | 0.3333 | 0.5000 | 0.5833 | 0.4215 |
| section 900 | 0.2917 | 0.5417 | 0.5417 | 0.4097 |
| section 1200 | 0.2500 | 0.5000 | 0.5000 | 0.3611 |
| fixed 600 | 0.1250 | 0.4583 | 0.5417 | 0.2847 |
| fixed 900 | 0.2083 | 0.5417 | 0.7083 | 0.3778 |
| fixed 1200 | 0.3333 | 0.6667 | 0.7500 | 0.4889 |

The best retrieval variant in the remapped A/B was `fixed_1200 + BGE-M3 + hybrid`.

After canonical regeneration with fixed 1200-char chunks, the then-standard official retrieval was:

| Canonical path | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| fixed 1200 regenerated eval/train/RAFT | 0.2917 | 0.6250 | 0.7083 | 0.4472 |

This was later superseded by the header-clean fixed 1200 canonical promotion:

| Canonical path | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| header-clean fixed 1200 | 0.3333 | 0.6250 | 0.6667 | 0.4736 |

## Rank Mode Check

For the best chunking candidate:

| Variant | Rank mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|
| fixed 1200 | lexical_first | 0.1667 | 0.5833 | 0.7083 | 0.3743 |
| fixed 1200 | semantic | 0.2083 | 0.2917 | 0.3333 | 0.2444 |
| fixed 1200 | hybrid | 0.3333 | 0.6667 | 0.7500 | 0.4889 |

The current simple hybrid ranker remains the best of the implemented rank modes.

## Answer-Level Check

`fixed_1200 + BGE-M3 + hybrid` answer evaluation:

| Metric | baseline 1600 | fixed 1200 |
|---|---:|---:|
| answerability accuracy | 1.0000 | 1.0000 |
| citation hit | 0.3667 | 0.4667 |
| citation recall | 0.3667 | 0.4667 |
| answer relevance | 0.3460 | 0.4157 |
| atomic fact support | 1.0000 | 0.9926 |

Citation quality improves, while atomic fact support drops slightly on the fixed 1200 variant. This should be treated as a retrieval improvement, not as final answer-generation quality.

## Row-Level Changes

Compared with the 1600-char baseline, `fixed_1200` newly retrieves `official_eval_0004` within top 5 and improves ranks for `0009`, `0013`, `0014`, and `0024`.

It worsens rank, but keeps a top-5 hit, for `0003`, `0015`, and `0016`.

## Interpretation

The first section-aware heuristic was too aggressive for the flat official pages. It created many chunks and reduced top-5 exact chunk recall. The simpler fixed-window 1200-char variant became the canonical baseline because it improved the remapped A/B result without requiring section reconstruction. After promotion, the regenerated held-out eval is slightly different, so the current canonical score is lower than the historical remapped A/B score but uses a cleaner end-to-end evidence ID path.

## Reproduction

```powershell
# Historical A/B variant
python src/prepare_chunks.py --docs data/raw/official_docs.jsonl --output data/processed/official_doc_chunks_fixed_1200.jsonl --max-chars 1200 --overlap-chars 80
python src/remap_eval_chunks.py --eval-set data/processed/official_eval_set.jsonl --chunks data/processed/official_doc_chunks_fixed_1200.jsonl --output data/processed/official_eval_set_fixed_1200.jsonl
python src/build_index.py --docs data/processed/official_doc_chunks_fixed_1200.jsonl --persist-dir outputs/chroma_official_chunks_fixed_1200 --model-name BAAI/bge-m3 --reset
python src/evaluate.py --eval-set data/processed/official_eval_set_fixed_1200.jsonl --persist-dir outputs/chroma_official_chunks_fixed_1200 --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_fixed_1200_hybrid.json

# Canonical promotion
python src/prepare_chunks.py --docs data/raw/official_docs.jsonl --output data/processed/official_doc_chunks.jsonl --max-chars 1200 --overlap-chars 80
python src/make_official_eval_set.py --chunks data/processed/official_doc_chunks.jsonl --output data/processed/official_eval_set.jsonl --train-output data/processed/official_train_qa.jsonl --answerable-limit 24 --train-limit 48
python src/make_raft_dataset.py --docs data/processed/official_doc_chunks.jsonl --qa data/processed/official_train_qa.jsonl --exclude-eval-set data/processed/official_eval_set.jsonl --output data/processed/official_raft_sample.jsonl --max-rows 52
python src/build_index.py --docs data/processed/official_doc_chunks.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --reset
python src/evaluate.py --eval-set data/processed/official_eval_set.jsonl --persist-dir outputs/chroma_official_chunks --model-name BAAI/bge-m3 --rank-mode hybrid --top-k 5 --output outputs/official_eval_report.json
```
