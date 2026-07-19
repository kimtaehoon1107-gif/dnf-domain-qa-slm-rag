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
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "entailment-control-builder-v3.1.0"
CASE_SCHEMA_VERSION = "entailment-control-case-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-control-manifest-v3.1"
LABELS = ("support", "contradiction", "insufficient")
SOURCE_IDS = (
    "dnf_account_policy",
    "dnf_event",
    "dnf_faq",
    "dnf_game_guide",
    "dnf_monthly_item",
    "dnf_notice",
    "dnf_seria_shop",
    "dnf_update",
)

DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/build_entailment_pilot.py")

# One explicit, reviewable proposition change per source. These are controlled
# counterfactuals, not naturally occurring user claims.
CONTRADICTION_REPLACEMENTS = {
    "dnf_account_policy": ("100일 게임 이용제한", "10일 게임 이용제한"),
    "dnf_event": ("2026년 7월 30일 06시", "2026년 7월 31일 06시"),
    "dnf_faq": ("주간 1회 무료 탐사", "주간 2회 무료 탐사"),
    "dnf_game_guide": ("1세라 = 1원", "1세라 = 10원"),
    "dnf_monthly_item": ("4,000만 골드", "5,000만 골드"),
    "dnf_notice": ("외부 메신저를 통한 거래를 유도하며", "외부 메신저를 통한 거래를 유도하지 않으며"),
    "dnf_seria_shop": ("한글 6자, 영문 12자", "한글 8자, 영문 16자"),
    "dnf_update": ("일각수 크라켄의 촉수가 제거됩니다", "일각수 크라켄의 촉수는 제거되지 않습니다"),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def select_seed_rows(dev_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in dev_rows
        if row["answerability"] == "true"
        and row["query_kind"] == "single_fact"
        and len(row["source_ids"]) == 1
        and len(row["evidence_groups"]) == 1
        and len(row["evidence_groups"][0].get("evidence_span", "")) <= 350
    ]
    selected = []
    for source_id in SOURCE_IDS:
        source_rows = sorted(
            (row for row in candidates if row["source_ids"] == [source_id]),
            key=lambda row: row["dev_id"],
        )
        if not source_rows:
            raise RuntimeError(f"No controlled entailment seed for {source_id}")
        selected.append(source_rows[0])
    return selected


def _contradiction_claim(source_id: str, gold_answer: str) -> tuple[str, dict[str, str]]:
    old, new = CONTRADICTION_REPLACEMENTS[source_id]
    if gold_answer.count(old) != 1:
        raise RuntimeError(
            f"Expected one contradiction target for {source_id}: {old!r}"
        )
    return gold_answer.replace(old, new, 1), {"from": old, "to": new}


def _case_id(payload: dict[str, Any]) -> str:
    return "entailment_case_sha256_" + _sha256_bytes(_canonical_json_bytes(payload))


def build_cases(dev_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeds = select_seed_rows(dev_rows)
    cases = []
    for source_ordinal, seed in enumerate(seeds):
        source_id = seed["source_ids"][0]
        evidence_text = seed["evidence_groups"][0]["evidence_span"]
        next_seed = seeds[(source_ordinal + 1) % len(seeds)]
        contradiction, mutation = _contradiction_claim(
            source_id, seed["gold_answer"]
        )
        variants = (
            ("support", seed["gold_answer"], "direct_gold_answer", None, None),
            (
                "contradiction",
                contradiction,
                "deterministic_single_mutation",
                mutation,
                None,
            ),
            (
                "insufficient",
                next_seed["gold_answer"],
                "cross_source_rotation",
                None,
                next_seed["source_ids"][0],
            ),
        )
        for label, claim, origin, case_mutation, rotated_source in variants:
            case_ordinal = len(cases)
            payload = {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_ordinal": case_ordinal,
                "source_ordinal": source_ordinal,
                "source_id": source_id,
                "dev_id": seed["dev_id"],
                "question": seed["question"],
                "evidence_text": evidence_text,
                "claim_text": claim,
                "label": label,
                "label_origin": origin,
                "mutation": case_mutation,
                "rotated_claim_source_id": rotated_source,
                "human_review_status": "agent_constructed_control",
                "training_allowed": False,
                "final_benchmark_eligible": False,
            }
            cases.append({**payload, "case_id": _case_id(payload)})
    return cases


def freeze_cases(
    root: Path,
    cases: list[dict[str, Any]],
    input_paths: dict[str, Path],
) -> dict[str, Any]:
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    output_dir = root / "data/v3/evidence"
    case_bytes = _serialize_jsonl(cases, lambda row: row["case_ordinal"])
    case_sha = _sha256_bytes(case_bytes)
    case_path = output_dir / f"entailment_control_cases_{case_sha}.jsonl"
    write_immutable(case_path, case_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "selection_contract": {
            "source_ids": list(SOURCE_IDS),
            "labels": list(LABELS),
            "candidate_filters": {
                "answerability": "true",
                "query_kind": "single_fact",
                "source_id_count": 1,
                "evidence_group_count": 1,
                "max_evidence_span_chars": 350,
            },
            "selection_order": "minimum dev_id per source_id",
            "contradiction_rules": CONTRADICTION_REPLACEMENTS,
            "insufficient_rule": "next source gold_answer in SOURCE_IDS cyclic order",
        },
        "cases": {
            "path": _relative(root, case_path),
            "sha256": case_sha,
            "row_count": len(cases),
            "label_counts": {
                label: sum(row["label"] == label for row in cases)
                for label in LABELS
            },
            "source_count": len({row["source_id"] for row in cases}),
        },
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "natural_distribution_claim": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"entailment_control_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "cases_path": str(case_path),
        "cases_sha256": case_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "row_count": len(cases),
    }


def build_and_freeze(
    root: Path, dev_path: Path, builder_source_path: Path
) -> dict[str, Any]:
    cases = build_cases(read_jsonl(dev_path))
    return freeze_cases(
        root,
        cases,
        {"retrieval_dev": dev_path, "builder_source": builder_source_path},
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build v3 controlled entailment cases")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(), args.dev_set.resolve(), args.builder_source.resolve()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
