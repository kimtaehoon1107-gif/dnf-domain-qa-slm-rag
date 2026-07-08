# Problem Definition

## Background

Dungeon & Fighter users ask questions about patch notes, notices, events, account/payment issues, operation policy, known bugs, items, characters, and game systems. A generic chatbot can easily hallucinate dates, rewards, item names, policy details, or personalized account state.

This v2 project uses the earlier `dnf-llm-eval` repository as the v1 baseline and builds a more complete DNF document QA workflow around official documents, answerability, evidence, and evaluation.

## Goal

Given a user question, the system should:

1. retrieve relevant DNF documents or chunks,
2. decide whether the question is answerable from collected evidence,
3. answer only from evidence when possible,
4. refuse or mark insufficient evidence when necessary,
5. return citations for the evidence used.

Target response shape:

```json
{
  "intent": "patch_note",
  "answerability": "true",
  "answer": "공식 문서 근거 기반 답변",
  "evidence": ["official_update_2926911__chunk_001"],
  "caution": "이 답변은 수집된 문서와 검색 결과 기준입니다."
}
```

## Non-goals

- Do not claim real-time account status, auction prices, or private user state.
- Do not invent information outside collected documents.
- Do not present Qwen/tiny LoRA smoke runs as final tuned-SLM quality.
- Do not tune chunking/ranking from the old title-derived eval; use the fact-based eval first.

## Scope

Intent taxonomy:

- `patch_note`
- `notice`
- `event`
- `game_system`
- `character_item`
- `operation_policy`
- `account_payment`
- `bug_known_issue`
- `recommendation`
- `unknown`

Answerability labels:

- `true`: evidence directly supports an answer
- `partial`: evidence supports only part of the answer
- `false`: evidence is insufficient or the request is out of scope

## Success Criteria

MVP success:

- JSONL data files parse successfully.
- Chroma indexes build for synthetic docs, official docs, and official chunks.
- Retrieval evaluation reports `hit_rate@k` and MRR.
- Official eval uses body-fact questions with `expected_chunk_ids`.
- Gradio can show retrieved evidence and a grounded response.

Quality-stage success:

- official eval is not title-derived and includes `gold_answer` and `evidence_span`.
- official RAFT training data has no held-out eval parent/chunk leakage.
- LoRA training masks prompt/evidence tokens and trains only on the answer completion.
- RAG-only, LLM-RAG, and tuned-SLM can be compared on the same held-out eval set.
- Failure analysis clearly separates retrieval failure, answerability failure, citation failure, and unsupported generation.

## Portfolio Message

This project demonstrates data construction, labeling design, retrieval, grounded generation, answerability judgment, RAFT data creation, LoRA/QLoRA readiness, and evaluation design. The current harder official eval exposes retrieval weakness instead of hiding it, which is a feature of the project rather than a defect.
