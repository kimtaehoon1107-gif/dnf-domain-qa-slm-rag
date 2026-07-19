from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.build_entailment_pilot import LABELS, SOURCE_IDS
from src.v3.collect_details import _canonical_json_bytes, write_immutable


EVALUATOR_VERSION = "entailment-control-evaluator-v3.1.0"
REPORT_SCHEMA_VERSION = "entailment-control-report-v3.1"
ACCURACY_GATE = 0.80
LABEL_RECALL_GATE = 0.75

DEFAULT_CASES = Path(
    "data/v3/evidence/"
    "entailment_control_cases_4d7d0343529edb97a3d678d9e4f71752626bb8c28e26af8f77a51a03e5dc949a.jsonl"
)
DEFAULT_CASE_MANIFEST = Path(
    "data/v3/evidence/"
    "entailment_control_manifest_1cab8d50cffc17caefa83614018c637fb617156af3be8d8e898c39083c4800d0.json"
)
DEFAULT_SCORES = Path(
    "data/v3/evidence/"
    "entailment_control_scores_f7c818a95d21996ab0f150317b0f43cf93b567b9ad5869ce6d02a0951e03b663.jsonl"
)
DEFAULT_SCORE_MANIFEST = Path(
    "data/v3/evidence/"
    "entailment_control_score_manifest_1c4d63e993cfa8d7fb0726c397d67fc003c12bdca7e5b0ef247602e41d042c3b.json"
)
DEFAULT_LATENCY = Path(
    "reports/v3/"
    "entailment_control_latency_064bf56c26731577b2f76cb588ae3f7d2f014f68292b7f75de699a03e85d009e.json"
)
DEFAULT_EVALUATOR_SOURCE = Path("src/v3/evaluate_entailment_pilot.py")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("No entailment score rows")
    model_keys = sorted(rows[0]["model_predictions"])
    if any(sorted(row["model_predictions"]) != model_keys for row in rows):
        raise RuntimeError("Entailment score rows have inconsistent model keys")
    models = {}
    for model_key in model_keys:
        confusion = {
            gold: {predicted: 0 for predicted in LABELS} for gold in LABELS
        }
        confidence_sum = 0.0
        for row in rows:
            gold = row["gold_label"]
            prediction = row["model_predictions"][model_key]
            predicted = prediction["predicted_label"]
            confusion[gold][predicted] += 1
            confidence_sum += prediction["probabilities"][predicted]
        correct = sum(confusion[label][label] for label in LABELS)
        per_label = {}
        for label in LABELS:
            true_positive = confusion[label][label]
            gold_total = sum(confusion[label].values())
            predicted_total = sum(confusion[gold][label] for gold in LABELS)
            precision = true_positive / predicted_total if predicted_total else 0.0
            recall = true_positive / gold_total if gold_total else 0.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision + recall
                else 0.0
            )
            per_label[label] = {
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
                "support": gold_total,
            }
        models[model_key] = {
            "row_count": len(rows),
            "correct_count": correct,
            "accuracy": round(correct / len(rows), 6),
            "macro_f1": round(
                sum(per_label[label]["f1"] for label in LABELS) / len(LABELS),
                6,
            ),
            "mean_predicted_confidence": round(confidence_sum / len(rows), 6),
            "per_label": per_label,
            "confusion": confusion,
        }
    return {"row_count": len(rows), "models": models}


def audit(
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    cases_by_id = {row["case_id"]: row for row in cases}
    rows_by_id = {row["case_id"]: row for row in rows}
    probability_valid = True
    for row in rows:
        for prediction in row["model_predictions"].values():
            values = prediction["probabilities"]
            probability_valid &= set(values) == set(LABELS)
            probability_valid &= abs(sum(values.values()) - 1.0) <= 1e-6
    integrity_gates = {
        "case_count_24": len(cases) == 24,
        "score_count_24": len(rows) == 24,
        "case_ids_align": set(cases_by_id) == set(rows_by_id),
        "case_ordinals_contiguous": [row["case_ordinal"] for row in cases]
        == list(range(24)),
        "label_counts_8_each": all(
            sum(row["label"] == label for row in cases) == 8 for label in LABELS
        ),
        "source_count_8": {row["source_id"] for row in cases} == set(SOURCE_IDS),
        "probabilities_valid": probability_valid,
        "labels_preserved": all(
            rows_by_id[case_id]["gold_label"] == case["label"]
            for case_id, case in cases_by_id.items()
        ),
        "training_leak_0": not any(
            row["training_allowed"] for row in cases + rows
        ),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in cases + rows
        ),
    }
    model_gates = {}
    for model_key, model_metrics in metrics["models"].items():
        gates = {
            "accuracy_at_least_0_80": model_metrics["accuracy"] >= ACCURACY_GATE,
            **{
                f"{label}_recall_at_least_0_75": model_metrics["per_label"][label][
                    "recall"
                ]
                >= LABEL_RECALL_GATE
                for label in LABELS
            },
        }
        model_gates[model_key] = {"gates": gates, "pass": all(gates.values())}
    passing = [key for key, value in model_gates.items() if value["pass"]]
    selected = (
        sorted(
            passing,
            key=lambda key: (-metrics["models"][key]["accuracy"], key),
        )[0]
        if passing
        else None
    )
    production_gates = {
        "natural_claim_distribution_measured": False,
        "human_label_review_complete": False,
        "independent_holdout_measured": False,
        "confidence_calibration_measured": False,
        "runtime_generator_integration_tested": False,
    }
    return {
        "integrity_gates": integrity_gates,
        "integrity_pass": all(integrity_gates.values()),
        "model_development_gates": model_gates,
        "controlled_candidate_pass": bool(passing),
        "selected_controlled_candidate": selected,
        "production_gates": production_gates,
        "production_pass": all(production_gates.values()),
    }


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for model_key, metrics in report["metrics"]["models"].items():
        rows.append(
            f"| {model_key} | {metrics['correct_count']}/24 | "
            f"{metrics['accuracy']} | {metrics['per_label']['support']['recall']} | "
            f"{metrics['per_label']['contradiction']['recall']} | "
            f"{metrics['per_label']['insufficient']['recall']} | {metrics['macro_f1']} |"
        )
    latency_rows = []
    for latency in report["latency"]["models"]:
        latency_rows.append(
            f"| {latency['model_key']} | {latency['inference_seconds']} | "
            f"{latency['pairs_per_second']} | {latency['peak_cuda_memory_bytes']} |"
        )
    return f"""# DNF RAG v3 Controlled Entailment Verifier Pilot

## Decision

- Artifact integrity: **{report['decision']['artifact_integrity']}**
- Controlled verifier development candidate: **{report['decision']['controlled_verifier_development']}**
- Selected controlled candidate: **{report['decision']['selected_candidate']}**
- Production verifier: **{report['decision']['production_verifier']}**
- Generator entry: **{report['decision']['generator_entry']}**
- Final benchmark: **{report['decision']['final_benchmark']}**

## Controlled results

| model | correct | accuracy | support recall | contradiction recall | insufficient recall | macro F1 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

The 24 cases contain eight official evidence/gold-answer support pairs, eight explicit single-mutation counterfactuals, and eight cross-source rotated insufficient pairs. These labels are agent-constructed controls and do not estimate natural user-claim performance.

## Observed batch cost

| model | inference seconds | pairs/second | peak CUDA bytes |
|---|---:|---:|---:|
{chr(10).join(latency_rows)}

These values are batch throughput observations, not online p50/p95 latency.

## Limits and next gate

Production remains NO-GO until a separately human-reviewed natural claim set measures support, contradiction, and insufficient cases; confidence calibration and runtime integration also remain unmeasured. No Generator, Router, training, or frozen blind evaluation was run in this cycle.

## Artifacts

- cases: `{report['artifacts']['cases_path']}`
- scores: `{report['artifacts']['scores_path']}`
- score manifest: `{report['artifacts']['score_manifest_path']}`
"""


def build_and_freeze(
    root: Path,
    cases_path: Path,
    case_manifest_path: Path,
    scores_path: Path,
    score_manifest_path: Path,
    latency_path: Path,
    evaluator_source_path: Path,
) -> dict[str, Any]:
    input_paths = {
        "cases": cases_path,
        "case_manifest": case_manifest_path,
        "scores": scores_path,
        "score_manifest": score_manifest_path,
        "latency": latency_path,
        "evaluator_source": evaluator_source_path,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    cases = read_jsonl(cases_path)
    rows = read_jsonl(scores_path)
    metrics = aggregate(rows)
    gates = audit(cases, rows, metrics)
    if not gates["integrity_pass"]:
        raise RuntimeError("Controlled entailment artifact integrity failed")
    latency = json.loads(latency_path.read_text(encoding="utf-8"))
    candidate = gates["selected_controlled_candidate"]
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "decision": {
            "artifact_integrity": "GO",
            "controlled_verifier_development": "GO"
            if gates["controlled_candidate_pass"]
            else "NO-GO",
            "selected_candidate": candidate,
            "production_verifier": "NO-GO",
            "generator_entry": "NO-GO",
            "human_reviewed_natural_set": "PENDING",
            "final_benchmark": "NO-GO",
        },
        "predeclared_development_gates": {
            "accuracy": ACCURACY_GATE,
            "per_label_recall": LABEL_RECALL_GATE,
        },
        "metrics": metrics,
        "audit": gates,
        "latency": latency,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "artifacts": {
            "cases_path": _relative(root, cases_path),
            "cases_sha256": input_hashes["cases"],
            "scores_path": _relative(root, scores_path),
            "scores_sha256": input_hashes["scores"],
            "score_manifest_path": _relative(root, score_manifest_path),
            "score_manifest_sha256": input_hashes["score_manifest"],
        },
        "not_measured": [
            "human_reviewed_natural_claim_performance",
            "independent_holdout",
            "confidence_calibration",
            "online_latency_p50_p95",
            "generator_integration",
            "final_blind_performance",
        ],
    }
    reports_dir = root / "reports/v3"
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_verifier_pilot_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_verifier_pilot_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
        "metrics": metrics,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Evaluate v3 controlled NLI pilot")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--cases", type=Path, default=root / DEFAULT_CASES)
    parser.add_argument(
        "--case-manifest", type=Path, default=root / DEFAULT_CASE_MANIFEST
    )
    parser.add_argument("--scores", type=Path, default=root / DEFAULT_SCORES)
    parser.add_argument(
        "--score-manifest", type=Path, default=root / DEFAULT_SCORE_MANIFEST
    )
    parser.add_argument("--latency", type=Path, default=root / DEFAULT_LATENCY)
    parser.add_argument(
        "--evaluator-source", type=Path, default=root / DEFAULT_EVALUATOR_SOURCE
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.cases.resolve(),
        args.case_manifest.resolve(),
        args.scores.resolve(),
        args.score_manifest.resolve(),
        args.latency.resolve(),
        args.evaluator_source.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
