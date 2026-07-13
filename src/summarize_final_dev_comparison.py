from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count(rate: float | None, total: int) -> int | None:
    return round(float(rate) * total) if rate is not None else None


def arm_summary(prefix: Path) -> dict[str, Any]:
    fresh_smoke = read_json(Path(f"{prefix}_fresh_dev.json"))
    fresh_quality = read_json(Path(f"{prefix}_fresh_dev_quality.json"))
    partial_smoke = read_json(Path(f"{prefix}_partial_dev.json"))
    partial_quality = read_json(Path(f"{prefix}_partial_dev_quality.json"))
    requirements = read_json(Path(f"{prefix}_partial_requirements.json"))

    fresh_smoke_summary = fresh_smoke["summary"]
    fresh_quality_summary = fresh_quality["summary"]
    partial_smoke_summary = partial_smoke["summary"]
    partial_quality_summary = partial_quality["summary"]
    requirement_summary = requirements["summary"]
    return {
        "generator_mode": fresh_smoke.get("generator_mode", "tuned_slm"),
        "model_name": fresh_smoke.get("model_name"),
        "adapter_dir": fresh_smoke.get("adapter_dir") or None,
        "config": {
            "embedding_model": fresh_smoke["embedding_model_name"],
            "rank_mode": fresh_smoke["rank_mode"],
            "top_k": fresh_smoke["top_k"],
            "candidate_k": fresh_smoke["candidate_k"],
            "max_doc_chars": fresh_smoke["max_doc_chars"],
            "max_new_tokens": fresh_smoke["max_new_tokens"],
            "instruction_mode": fresh_smoke["instruction_mode"],
            "context_mode": fresh_smoke["context_mode"],
            "seed": fresh_smoke["seed"],
            "deterministic": fresh_smoke["deterministic"],
        },
        "fresh_dev": {
            "rows": fresh_smoke["rows"],
            "retrieval_hit": count(
                fresh_smoke_summary["retrieval_expected_hit_rate"], 22
            ),
            "answerability_field": count(
                fresh_smoke_summary["answerability_field_rate"], 30
            ),
            "true_correct": int(
                fresh_smoke_summary["answerability_by_label"]["true"]["correct"]
            ),
            "partial_correct": int(
                fresh_smoke_summary["answerability_by_label"]["partial"]["correct"]
            ),
            "false_correct": int(
                fresh_smoke_summary["answerability_by_label"]["false"]["correct"]
            ),
            "exact_citation": count(
                fresh_quality_summary["exact_citation_set_match_rate"], 22
            ),
            "partial_joint": count(
                fresh_quality_summary["partial_joint_success_rate"], 6
            ),
            "false_joint": count(
                fresh_quality_summary["false_joint_correct_rate"], 8
            ),
            "unsafe_answers": int(fresh_quality["counts"]["unsafe_answers"]),
            "avg_generation_latency_sec": fresh_smoke_summary[
                "avg_generation_latency_sec"
            ],
            "device": fresh_smoke["device"],
        },
        "human_partial_dev": {
            "rows": partial_smoke["rows"],
            "retrieval_hit": count(
                partial_smoke_summary["retrieval_expected_hit_rate"], 20
            ),
            "answerability_field": count(
                partial_smoke_summary["answerability_field_rate"], 20
            ),
            "exact_citation": count(
                partial_quality_summary["exact_citation_set_match_rate"], 20
            ),
            "partial_joint": count(
                partial_quality_summary["partial_joint_success_rate"], 20
            ),
            "strict_requirement_joint": count(
                requirement_summary["partial_requirement_joint_success_rate"], 20
            ),
            "grounded_answered_and_cited": count(
                requirement_summary["grounded_slot_answer_and_citation_rate"], 31
            ),
            "unsupported_explicit_abstention": count(
                requirement_summary["unsupported_slot_abstention_rate"], 21
            ),
            "unsupported_over_answer": count(
                requirement_summary["unsupported_slot_over_answer_rate"], 21
            ),
            "avg_generation_latency_sec": partial_smoke_summary[
                "avg_generation_latency_sec"
            ],
            "device": partial_smoke["device"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize the final three-arm dev comparison.")
    parser.add_argument("--rag-prefix", type=Path, required=True)
    parser.add_argument("--base-prefix", type=Path, required=True)
    parser.add_argument("--tuned-prefix", type=Path, required=True)
    parser.add_argument("--release-decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = {
        "report_schema_version": 1,
        "scope": "development_only_no_blind",
        "arms": {
            "rag_only": arm_summary(args.rag_prefix),
            "base_slm_rag": arm_summary(args.base_prefix),
            "clean_tuned_slm_rag": arm_summary(args.tuned_prefix),
        },
        "release_decision": read_json(args.release_decision),
        "notes": [
            "fresh_dev is adaptive development data, not a final held-out test.",
            "The frozen blind was not queried because the clean tuned checkpoints failed predeclared dev gates.",
            "Latency is descriptive only; RAG-only is rule-based and model arms include generation.",
            "Strict schema failure makes base-SLM structured metrics zero even when raw prose contains an answer.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
