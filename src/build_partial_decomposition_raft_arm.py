from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def index_unique(rows: list[dict[str, Any]], key: str, source: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value or value in indexed:
            raise ValueError(f"{source} has missing or duplicate {key}: {value!r}")
        indexed[value] = row
    return indexed


def build_controlled_raft(
    baseline_rows: list[dict[str, Any]],
    generated_rows: list[dict[str, Any]],
    reviewed_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    baseline = index_unique(baseline_rows, "source_qa_id", "baseline RAFT")
    generated = index_unique(generated_rows, "source_qa_id", "generated RAFT")
    reviewed = index_unique(reviewed_rows, "qa_id", "reviewed decomposition QA")

    missing_baseline = sorted(set(baseline) - set(generated))
    new_ids = set(generated) - set(baseline)
    if missing_baseline:
        raise ValueError(f"Generated RAFT is missing baseline source rows: {missing_baseline[:10]}")
    if new_ids != set(reviewed):
        raise ValueError(
            "Generated RAFT additions do not match reviewed decomposition IDs: "
            f"missing={sorted(set(reviewed) - new_ids)}, extra={sorted(new_ids - set(reviewed))}"
        )

    additions = []
    for row in generated_rows:
        source_id = str(row["source_qa_id"])
        if source_id not in new_ids:
            continue
        if str(row.get("source_eval_type")) != "partial_decomposition_train":
            raise ValueError(f"New RAFT row has the wrong source type: {source_id}")
        if str(row.get("answerability")) != "partial":
            raise ValueError(f"New RAFT row is not Partial: {source_id}")
        additions.append(dict(row))

    combined = [dict(row) for row in baseline_rows] + additions
    for index, row in enumerate(combined, start=1):
        row["raft_id"] = f"raft_{index:04d}"
    return combined, {
        "baseline_rows_preserved": len(baseline_rows),
        "reviewed_rows_appended": len(additions),
        "rows": len(combined),
        "unique_source_qa_ids": len(baseline) + len(new_ids),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preserve the checkpoint-250 RAFT rows and append only reviewed decomposition rows."
    )
    parser.add_argument(
        "--baseline-raft",
        type=Path,
        default=Path("data/processed/domain_raft_hard_negative_answer_filtered_blind_safe_v2.jsonl"),
    )
    parser.add_argument(
        "--generated-raft",
        type=Path,
        default=Path("data/processed/domain_raft_partial_decomposition_arm_generated.jsonl"),
    )
    parser.add_argument(
        "--reviewed-qa",
        type=Path,
        default=Path("data/processed/domain_partial_decomposition_train_reviewed.jsonl"),
    )
    parser.add_argument(
        "--reviewed-manifest",
        type=Path,
        default=Path("reports/partial_decomposition_train_reviewed_manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/domain_raft_partial_decomposition_arm.jsonl"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("reports/domain_raft_partial_decomposition_arm_manifest.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reviewed_manifest = json.loads(args.reviewed_manifest.read_text(encoding="utf-8"))
    if reviewed_manifest.get("status") != "frozen_reviewed_training_only":
        raise ValueError("Reviewed decomposition manifest is not frozen for training.")
    if reviewed_manifest.get("output_sha256") != sha256(args.reviewed_qa):
        raise ValueError("Reviewed decomposition QA no longer matches its manifest.")

    combined, summary = build_controlled_raft(
        read_jsonl(args.baseline_raft),
        read_jsonl(args.generated_raft),
        read_jsonl(args.reviewed_qa),
    )
    write_jsonl(args.output, combined)
    manifest = {
        "status": "ready_for_gate_balance",
        "one_variable_intervention": "append_reviewed_partial_decomposition_rows",
        "baseline_raft": str(args.baseline_raft),
        "baseline_raft_sha256": sha256(args.baseline_raft),
        "generated_raft": str(args.generated_raft),
        "generated_raft_sha256": sha256(args.generated_raft),
        "reviewed_qa": str(args.reviewed_qa),
        "reviewed_qa_sha256": sha256(args.reviewed_qa),
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        **summary,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
