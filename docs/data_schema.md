# Data Schema

This project uses JSONL files so each row can be inspected, labeled, and regenerated independently.

## Document

Files:

- `data/raw/docs.jsonl`
- `data/raw/official_docs.jsonl`
- `data/processed/official_doc_chunks.jsonl`
- `data/processed/domain_doc_chunks.jsonl`

Required fields:

```json
{
  "doc_id": "official_update_2926911__chunk_001",
  "parent_doc_id": "official_update_2926911",
  "chunk_index": 1,
  "chunk_count": 2,
  "source_type": "official",
  "doc_type": "patch_note",
  "title": "4/9(목) 정기점검 업데이트 안내",
  "published_at": "2026-04-08",
  "effective_start": null,
  "effective_end": null,
  "source_url": "https://df.nexon.com/...",
  "tags": ["official", "update", "patch_note"],
  "text": "chunk text"
}
```

`parent_doc_id`, `chunk_index`, and `chunk_count` are required for chunked official documents.

## QA Row

File:

- `data/processed/qa_dataset.jsonl`
- `data/processed/official_train_qa.jsonl`
- `data/processed/domain_train_qa_expanded.jsonl`

Example:

```json
{
  "qa_id": "official_train_0001",
  "question": "공식 문서에서 7일간, 기간 관련 핵심 내용은 뭐야?",
  "intent": "event",
  "answerability": "true",
  "expected_answer": "여름맞이 7일간의 여정 이벤트 기간: 2026-06-04 ~ 2026-08-27.",
  "gold_answer": "여름맞이 7일간의 여정 이벤트 기간: 2026-06-04 ~ 2026-08-27.",
  "evidence_span": "여름맞이 7일간의 여정 이벤트 기간: 2026-06-04 ~ 2026-08-27.",
  "expected_doc_id": "official_event_event_card_006",
  "expected_chunk_id": "official_event_event_card_006__chunk_001",
  "expected_evidence_doc_ids": ["official_event_event_card_006"],
  "expected_chunk_ids": ["official_event_event_card_006__chunk_001"],
  "split": "train"
}
```

## Evaluation Row

File:

- `data/processed/eval_set.jsonl`
- `data/processed/official_eval_set.jsonl`
- `data/processed/domain_eval_set_expanded.jsonl`

The official eval set is chunk-level:

```json
{
  "eval_id": "official_eval_0001",
  "question": "공식 문서에서 잔여, 오류 관련 핵심 내용은 뭐야?",
  "intent": "patch_note",
  "answerability": "true",
  "expected_answer": "잔여 오류 중 ... 임시 조치 하였습니다.",
  "gold_answer": "잔여 오류 중 ... 임시 조치 하였습니다.",
  "evidence_span": "잔여 오류 중 ... 임시 조치 하였습니다.",
  "expected_doc_id": "official_update_2926911",
  "expected_chunk_id": "official_update_2926911__chunk_001",
  "expected_evidence_doc_ids": ["official_update_2926911"],
  "expected_chunk_ids": ["official_update_2926911__chunk_001"],
  "difficulty": "medium",
  "failure_focus": "item_name_or_numeric_value_error",
  "source_eval_type": "official_fact_chunk",
  "title_overlap_ratio": 0.0
}
```

Unanswerable/OOD/safety rows use empty evidence fields:

```json
{
  "eval_id": "official_eval_0028",
  "question": "오늘 서울 날씨 알려줘.",
  "answerability": "false",
  "expected_evidence_doc_ids": [],
  "expected_chunk_ids": [],
  "source_eval_type": "v1_safety_ood_port"
}
```

## RAFT Row

File:

- `data/processed/raft_train_sample.jsonl`
- `data/processed/official_raft_sample.jsonl`
- `data/processed/domain_raft_sample_expanded.jsonl`

Example:

```json
{
  "raft_id": "raft_0001",
  "instruction": "제공된 공식 문서 근거만 사용해 질문에 답하라...",
  "question": "공식 문서에서 7일간, 기간 관련 핵심 내용은 뭐야?",
  "documents": [
    {
      "doc_id": "official_event_event_card_006__chunk_001",
      "role": "gold",
      "title": "여름맞이 7일간의 여정",
      "text": "여름맞이 7일간의 여정 이벤트 기간: 2026-06-04 ~ 2026-08-27."
    },
    {
      "doc_id": "official_notice_2927769__chunk_001",
      "role": "distractor",
      "title": "6/18(목) 불량이용자 단속결과 안내",
      "text": "..."
    }
  ],
  "answer": "여름맞이 7일간의 여정 이벤트 기간: 2026-06-04 ~ 2026-08-27.",
  "citations": ["official_event_event_card_006__chunk_001"],
  "answerability": "true",
  "intent": "event",
  "source_split": "train",
  "expected_doc_id": "official_event_event_card_006",
  "expected_chunk_ids": ["official_event_event_card_006__chunk_001"]
}
```

Official RAFT must not include parent docs or chunks used in the held-out official eval set.
Expanded domain RAFT must not include parent docs or chunks used in `domain_eval_set_expanded.jsonl`; this is checked by `src/validate_domain_dataset.py`.

## Metrics

Retrieval:

- `hit_rate@1`
- `hit_rate@3`
- `hit_rate@k`
- MRR

`hit_rate@k` means at least one expected evidence ID appears in top-k. When `expected_chunk_ids` exist, scoring is chunk-level. Otherwise it falls back to parent document IDs.

Answer evaluation:

- answerability accuracy
- citation hit/precision/recall
- context relevance
- answer relevance
- faithfulness-style atomic fact support
- unsupported fact rows

## Label Studio Export

Label Studio import/export helpers:

- `src/label_studio_io.py export-tasks`
- `src/label_studio_io.py convert-export`

Normalized export rows include:

- `item_id`
- `question`
- `intent`
- `answerability`
- `evidence_quality`
- `evidence_doc_ids`
- `corrected_answer`
- `review_notes`
- `source_split`
- `source_payload`
