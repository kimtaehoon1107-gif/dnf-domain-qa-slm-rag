import argparse
import json
import sys
from pathlib import Path

from io_utils import read_jsonl
from retrieve import retrieve
from retrieval_config import DEFAULT_EMBEDDING_MODEL, DEFAULT_RANK_MODE, RANK_MODES


def reciprocal_rank(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in expected_ids:
            return 1.0 / rank
    return 0.0


def expected_match_ids(row: dict) -> tuple[list[str], str]:
    chunk_ids = row.get("expected_chunk_ids") or []
    if row.get("expected_chunk_id"):
        chunk_ids = [row["expected_chunk_id"]]
    if chunk_ids:
        return [str(doc_id) for doc_id in chunk_ids], "chunk"
    return [str(doc_id) for doc_id in row.get("expected_evidence_doc_ids", [])], "parent_doc"


def evaluate_retrieval(
    eval_set_path: Path,
    persist_dir: Path,
    top_k: int,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    candidate_k: int | None = None,
    rank_mode: str = DEFAULT_RANK_MODE,
) -> dict:
    rows = read_jsonl(eval_set_path)
    answerable_rows = [row for row in rows if expected_match_ids(row)[0]]
    if not answerable_rows:
        raise ValueError("Evaluation set has no answerable rows with expected evidence.")

    hit_at_1_total = 0
    hit_at_3_total = 0
    hit_at_k_total = 0
    mrr_total = 0.0
    details = []

    for row in answerable_rows:
        hits = retrieve(
            row["question"],
            persist_dir=persist_dir,
            top_k=top_k,
            model_name=model_name,
            candidate_k=candidate_k,
            rank_mode=rank_mode,
        )
        retrieved_ids = [hit["doc_id"] for hit in hits]
        expected_ids, match_scope = expected_match_ids(row)
        if match_scope == "chunk":
            retrieved_match_ids = retrieved_ids
        else:
            retrieved_match_ids = [
                hit.get("metadata", {}).get("parent_doc_id") or hit["doc_id"]
                for hit in hits
            ]

        hit_at_1 = any(doc_id in retrieved_match_ids[:1] for doc_id in expected_ids)
        hit_at_3 = any(doc_id in retrieved_match_ids[:3] for doc_id in expected_ids)
        hit_at_k = any(doc_id in retrieved_match_ids[:top_k] for doc_id in expected_ids)
        rr = reciprocal_rank(retrieved_match_ids, expected_ids)

        hit_at_1_total += int(hit_at_1)
        hit_at_3_total += int(hit_at_3)
        hit_at_k_total += int(hit_at_k)
        mrr_total += rr

        details.append(
            {
                "eval_id": row["eval_id"],
                "question": row["question"],
                "expected": expected_ids,
                "match_scope": match_scope,
                "retrieved": retrieved_ids,
                "retrieved_match_ids": retrieved_match_ids,
                "hit_at_k": hit_at_k,
                "reciprocal_rank": rr,
            }
        )

    total = len(answerable_rows)
    report = {
        "total_answerable": total,
        "eval_set": str(eval_set_path),
        "persist_dir": str(persist_dir),
        "model_name": model_name,
        "rank_mode": rank_mode,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "metric_note": "hit_rate@k reports whether any expected evidence ID appears in the top-k results.",
        "hit_rate@1": hit_at_1_total / total,
        "mrr": mrr_total / total,
        "details": details,
    }
    if top_k >= 3:
        report["hit_rate@3"] = hit_at_3_total / total
    if top_k not in {1, 3}:
        report["hit_rate@k"] = hit_at_k_total / total
        report[f"hit_rate@{top_k}"] = hit_at_k_total / total
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against expected evidence IDs.")
    parser.add_argument("--eval-set", type=Path, default=Path("data/processed/eval_set.jsonl"))
    parser.add_argument("--persist-dir", type=Path, default=Path("outputs/chroma"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=None)
    parser.add_argument("--model-name", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rank-mode", choices=RANK_MODES, default=DEFAULT_RANK_MODE)
    parser.add_argument("--output", type=Path, default=Path("outputs/eval_report.json"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = evaluate_retrieval(
        args.eval_set,
        args.persist_dir,
        args.top_k,
        model_name=args.model_name,
        candidate_k=args.candidate_k,
        rank_mode=args.rank_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in report.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
