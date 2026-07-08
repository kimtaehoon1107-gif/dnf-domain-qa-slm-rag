# Portfolio Summary

## DNF Domain QA SLM/RAG v2

This project extends the earlier `dnf-llm-eval` baseline into a full domain QA workflow for Dungeon & Fighter official documents.

## What It Demonstrates

- Domain QA dataset design
- Intent, answerability, and evidence-quality labeling schema
- Official notice/update/event document collection
- Chunk-based RAG retrieval with Chroma, BGE-M3, and rank-mode ablation
- Fact-based held-out evaluation with `expected_chunk_ids`
- Lightweight RAGAS/FActScore-style answer evaluation
- Label Studio import/export workflow
- RAFT-style SLM training data with gold and distractor evidence
- LoRA/QLoRA training scaffold with completion-only masking
- Gradio demo with RAG-only and tuned-SLM modes

## Current Result

- synthetic docs: 30
- synthetic QA: 100
- synthetic eval: 30
- official docs: 63
- official chunks: 197
- official eval rows: 30
- official answerable fact rows: 24
- official train QA rows: 41
- official RAFT rows: 41
- expanded domain eval rows: 120
- fresh paraphrase/OOD eval rows: 30
- expanded domain RAFT rows: 300
- gate-balanced SLM RAFT rows: 456
- expanded review samples: 100
- synthetic retrieval hit@5: 1.0000
- official chunk retrieval hit@5: 0.6667 canonical
- expanded domain retrieval hit@1 / hit@5: 0.2556 / 0.3778
- synthetic answerability accuracy: 1.0000
- official answerability accuracy: 1.0000
- expanded domain answerability accuracy: 1.0000
- official citation recall: 0.4667
- expanded domain citation recall: 0.4417
- answerability classifier baseline accuracy: 0.8000
- LoRA dry-run: 41 official RAFT rows, `true=37`, `false=4`, completion-only masking
- tiny LoRA smoke: trained 2 rows and saved adapter
- tuned-SLM tiny inference smoke: adapter loaded and generated 1 row
- Qwen 0.5B domain LoRA Stage 1: trained 300 expanded RAFT rows on GPU, adapter saved
- Qwen 0.5B cite-first LoRA: fixed field compliance but failed answerability by parsing every row as `true`
- Qwen 0.5B gate-balanced LoRA: earlier 460-row adapter reached expanded eval answerability 120/120, citation hit when retrieval hit 0.7188
- Qwen 0.5B gate-balanced v2 LoRA: trained 456 fresh-clean RAFT rows, expanded eval answerability 120/120, official eval answerability 30/30
- fresh eval check: retrieval hit@3 0.9545, tuned-SLM answerability improved from 0.3000 to 0.4333, true questions 4/16
- smoke test: passed

## Why It Is More Than a Chatbot

The project separates data construction, labeling, retrieval, answerability, evaluation, and training-data expansion. The current harder eval intentionally exposes retrieval and SLM failure modes instead of hiding them: cite-first formatting fixed citations but broke structured refusal, then gate-balanced RAFT corrected answerability on the expanded eval, then fresh paraphrase/OOD evaluation exposed over-refusal on casual true questions. Fresh-clean v2 removes held-out leakage and improves the fresh slice slightly, but the next credibility gate is still adding train-only true paraphrase coverage without leaking the fresh eval.
