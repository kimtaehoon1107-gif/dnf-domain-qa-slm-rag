from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ARMS = ("control", "instruction_only", "hard_negative_only")
SETS = ("domain", "official", "fresh_dev")
ADAPTER_DIRS = {
    "control": "slm_lora_measurement_control_parent_group",
    "instruction_only": "slm_lora_measurement_instruction_only_parent_group",
    "hard_negative_only": "slm_lora_measurement_hard_negative_only_parent_group",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def label_accuracy(summary: dict[str, Any], label: str) -> float | None:
    stats = summary.get("answerability_by_label", {}).get(label)
    return stats.get("accuracy") if stats else None


def row_metrics(smoke: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    summary = smoke["summary"]
    q_summary = quality["summary"]
    return {
        "rows": smoke["rows"],
        "retrieval_expected_hit_rate": summary["retrieval_expected_hit_rate"],
        "usable_gold_hit_rate": summary.get("usable_gold_hit_rate"),
        "answerability_accuracy": summary["answerability_accuracy"],
        "true_accuracy": label_accuracy(summary, "true"),
        "partial_accuracy": label_accuracy(summary, "partial"),
        "false_accuracy": label_accuracy(summary, "false"),
        "exact_citation_precision_macro": q_summary["exact_citation_precision_macro"],
        "exact_citation_recall_macro": q_summary["exact_citation_recall_macro"],
        "partial_joint_success_rate": q_summary["partial_joint_success_rate"],
        "false_joint_correct_rate": q_summary["false_joint_correct_rate"],
        "unsafe_answer_rate_on_safety_false": q_summary["unsafe_answer_rate_on_safety_false"],
        "evidence_token_recall_in_answer_mean": q_summary["evidence_token_recall_in_answer_mean"],
        "avg_generation_latency_sec": summary["avg_generation_latency_sec"],
    }


def fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.3f}"


def markdown_table(result: dict[str, Any], eval_set: str) -> list[str]:
    lines = [
        f"### {eval_set}",
        "",
        "| arm | ans. acc | true | partial | false | exact citation | partial joint | false joint | evidence recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        row = result["hybrid"][arm][eval_set]
        lines.append(
            "| "
            + " | ".join(
                [
                    arm,
                    fmt(row["answerability_accuracy"]),
                    fmt(row["true_accuracy"]),
                    fmt(row["partial_accuracy"]),
                    fmt(row["false_accuracy"]),
                    fmt(row["exact_citation_recall_macro"]),
                    fmt(row["partial_joint_success_rate"]),
                    fmt(row["false_joint_correct_rate"]),
                    fmt(row["evidence_token_recall_in_answer_mean"]),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def build_report(outputs_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"training": {}, "hybrid": {}, "reranker_followup": {}}
    for arm in ARMS:
        manifest = read_json(outputs_dir / ADAPTER_DIRS[arm] / "training_manifest.json")
        result["training"][arm] = {
            "adapter_dir": str(outputs_dir / ADAPTER_DIRS[arm]),
            "git_commit": manifest["git_commit"],
            "train_file": manifest["train_file"],
            "train_file_sha256": manifest["train_file_sha256"],
            "prompt_instruction_sha256": manifest["prompt_instruction_sha256"],
            "train_rows": manifest["train_rows"],
            "dev_rows": manifest["dev_rows"],
            "dev_group_by": manifest["split"]["group_by"],
            "train_dev_parent_overlap": manifest["split"]["parent_doc_overlap"],
            "skipped_rows": manifest["skipped_train_rows"] + manifest["skipped_dev_rows"],
            "global_step": manifest["global_step"],
            "final_dev_loss": manifest["final_dev_loss"],
        }
        result["hybrid"][arm] = {}
        for eval_set in SETS:
            smoke = read_json(outputs_dir / f"controlled_{arm}_{eval_set}.json")
            quality = read_json(outputs_dir / f"controlled_{arm}_{eval_set}_quality.json")
            result["hybrid"][arm][eval_set] = row_metrics(smoke, quality)

    retrieval_invariants = {}
    for eval_set in SETS:
        values = {
            result["hybrid"][arm][eval_set]["retrieval_expected_hit_rate"]
            for arm in ARMS
        }
        retrieval_invariants[eval_set] = len(values) == 1

    for arm in ("control", "hard_negative_only"):
        result["reranker_followup"][arm] = {}
        for eval_set in ("domain", "fresh_dev"):
            smoke = read_json(outputs_dir / f"controlled_{arm}_reranker_{eval_set}.json")
            quality = read_json(outputs_dir / f"controlled_{arm}_reranker_{eval_set}_quality.json")
            result["reranker_followup"][arm][eval_set] = row_metrics(smoke, quality)

    result.update(
        {
            "status": "complete_no_promotion",
            "date": "2026-07-11",
            "evaluation_role": {
                "domain": "development",
                "official": "legacy compatibility development",
                "fresh_dev": "adaptive conversational development",
                "blind_test_v1_candidate": "pending human review; never evaluated",
            },
            "retrieval_invariants_passed": retrieval_invariants,
            "verdict": {
                "promoted_adapter": None,
                "gradio_default": "outputs/slm_lora_qwen_domain_v3_3",
                "instruction_only": "rejected: no partial-joint gain and no citation gain versus control",
                "hard_negative_only": "rejected: improved refusal but substantially harmed exact citation and content support",
                "reranker_default": "off",
                "reranker": "retrieval improved, but end-to-end control traded higher domain citation for worse false refusal and did not improve fresh citation",
                "next_training_artifact": "data/processed/domain_raft_hard_negative_answer_filtered_gate_balanced.jsonl",
                "next_training_gate": "human review the blind-test candidate and review answer-filtered negatives before any new training run",
            },
        }
    )
    return result


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Measurement-Repaired Controlled SLM Experiment",
        "",
        "## Scope",
        "",
        "All three arms use the same 408 unique QA groups, parent-document-held-out dev split, 900-character query-aware evidence window, two epochs, and deterministic evaluation. The pending blind-test candidate was not queried.",
        "",
        "- `control`: legacy instruction + random distractors",
        "- `instruction_only`: request-mix instruction + the same random-distractor recipe",
        "- `hard_negative_only`: legacy instruction + reranker-mined distractors",
        "",
        "## Hybrid Retrieval",
        "",
    ]
    for eval_set in SETS:
        lines.extend(markdown_table(result, eval_set))
    lines.extend(
        [
            "## Reranker Follow-up",
            "",
            "| arm | set | retrieval hit | exact citation | partial joint | false joint | evidence recall |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for arm in ("control", "hard_negative_only"):
        for eval_set in ("domain", "fresh_dev"):
            row = result["reranker_followup"][arm][eval_set]
            lines.append(
                f"| {arm} | {eval_set} | {fmt(row['retrieval_expected_hit_rate'])} | "
                f"{fmt(row['exact_citation_recall_macro'])} | {fmt(row['partial_joint_success_rate'])} | "
                f"{fmt(row['false_joint_correct_rate'])} | {fmt(row['evidence_token_recall_in_answer_mean'])} |"
            )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            "No new adapter is promoted. The instruction-only change improved some refusal rows but did not improve partial joint success or citation. The unfiltered hard-negative arm learned stronger refusal while losing evidence selection; diagnostics found valid duplicate evidence mislabeled as distractors.",
            "",
            "The Gradio default remains v3.3 and the reranker remains off. An answer-aware hard-negative artifact has been regenerated with exact/high-overlap evidence contamination removed, but it is intentionally not trained in this round.",
            "",
            "`fresh_paraphrase_eval_set.jsonl` is reported as `fresh_dev`, not a final blind test. The new blind candidate remains pending human review and was never passed to retrieval or generation.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize the measurement-repaired controlled SLM experiment.")
    parser.add_argument("--outputs-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--json-output", type=Path, default=Path("reports/controlled_training_results.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("docs/controlled_training_results.md"))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_report(args.outputs_dir)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "verdict": result["verdict"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
