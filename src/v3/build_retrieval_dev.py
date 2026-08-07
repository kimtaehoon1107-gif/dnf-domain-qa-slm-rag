from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


BUILDER_VERSION = "retrieval-dev-builder-v3.1.0"
SCHEMA_VERSION = "retrieval-dev-v3.1"
EXPECTED_ROW_COUNT = 63
EXPECTED_SOURCE_IDS = {
    "dnf_account_policy",
    "dnf_event",
    "dnf_faq",
    "dnf_game_guide",
    "dnf_monthly_item",
    "dnf_notice",
    "dnf_seria_shop",
    "dnf_update",
}
DEFAULT_AS_OF = "2026-07-18"


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def immutable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"immutable artifact collision: {path}")
        return
    path.write_bytes(data)


def freeze_jsonl(directory: Path, prefix: str, rows: list[dict[str, Any]]) -> tuple[Path, str]:
    data = jsonl_bytes(rows)
    digest = sha256_bytes(data)
    path = directory / f"{prefix}_{digest}.jsonl"
    immutable_write(path, data)
    return path, digest


def freeze_json(directory: Path, prefix: str, value: dict[str, Any]) -> tuple[Path, str]:
    data = canonical_json_bytes(value)
    digest = sha256_bytes(data)
    path = directory / f"{prefix}_{digest}.json"
    immutable_write(path, data)
    return path, digest


def freeze_markdown(directory: Path, prefix: str, text: str) -> tuple[Path, str]:
    data = (text.rstrip() + "\n").encode("utf-8")
    digest = sha256_bytes(data)
    path = directory / f"{prefix}_{digest}.md"
    immutable_write(path, data)
    return path, digest


def _row_index(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row[key]
        if value in index:
            raise RuntimeError(f"duplicate {label}: {value}")
        index[value] = row
    return index


def _matching_chunks(
    evidence_span: str,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    needle = normalize_text(evidence_span)
    return [row for row in chunks if needle in normalize_text(row["display_text"])]


def _evidence_group(
    group_number: int,
    evidence_span: str,
    matched_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    if not matched_chunks:
        raise RuntimeError(f"evidence did not map: {evidence_span[:80]}")
    parent_ids = sorted({row["parent_document_id"] for row in matched_chunks})
    if len(parent_ids) != 1:
        raise RuntimeError(
            f"evidence maps to multiple parents ({len(parent_ids)}): {evidence_span[:80]}"
        )
    return {
        "group_id": f"evidence_{group_number}",
        "evidence_span": normalize_text(evidence_span),
        "acceptable_chunk_ids": sorted(row["chunk_id"] for row in matched_chunks),
        "document_ids": parent_ids,
    }


def _direct_groups(
    seed: dict[str, Any],
    chunk_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for number, group in enumerate(seed.get("evidence_groups", []), start=1):
        chunk_ids = sorted(set(group["chunk_ids"]))
        unknown = [chunk_id for chunk_id in chunk_ids if chunk_id not in chunk_index]
        if unknown:
            raise RuntimeError(f"unknown direct chunk ids for {seed['seed_id']}: {unknown}")
        matched = [chunk_index[chunk_id] for chunk_id in chunk_ids]
        needle = normalize_text(group["evidence_span"])
        misses = [
            row["chunk_id"]
            for row in matched
            if needle not in normalize_text(row["display_text"])
        ]
        if misses:
            raise RuntimeError(f"direct evidence mismatch for {seed['seed_id']}: {misses}")
        groups.append(_evidence_group(number, group["evidence_span"], matched))
    return groups


def _query_policy(
    seed: dict[str, Any],
    query_kind: str,
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    statuses = sorted({row["status"] for row in documents})
    default_safe = query_kind == "unanswerable" or (
        bool(documents) and all(row["default_exposure"] for row in documents)
    )
    default_safe = default_safe and all(status not in {"expired", "superseded"} for status in statuses)
    default_safe = default_safe and query_kind not in {"historical_control", "preview_control"}
    default_only = seed.get("default_exposure_only", default_safe)
    as_of = seed.get("as_of")
    if "as_of" not in seed and default_only:
        as_of = DEFAULT_AS_OF
    return {
        "default_exposure_only": bool(default_only),
        "allowed_statuses": statuses or ["current", "upcoming"],
        "include_review_required": any(row.get("review_required", False) for row in chunks),
        "as_of": as_of,
    }


def _build_output_row(
    seed: dict[str, Any],
    base: dict[str, Any],
    groups: list[dict[str, Any]],
    chunk_index: dict[str, dict[str, Any]],
    document_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chunk_ids = sorted(
        {
            chunk_id
            for group in groups
            for chunk_id in group["acceptable_chunk_ids"]
        }
    )
    document_ids = sorted(
        {document_id for group in groups for document_id in group["document_ids"]}
    )
    target_chunks = [chunk_index[chunk_id] for chunk_id in chunk_ids]
    target_documents = [document_index[document_id] for document_id in document_ids]
    query_kind = seed.get("query_kind") or {
        "false": "unanswerable",
        "partial": "partial",
        "true": "single_fact",
    }[base["answerability"]]
    source_ids = sorted({row["source_id"] for row in target_documents})
    target_statuses = sorted({row["status"] for row in target_documents})
    gold_answer = seed.get("gold_answer", base.get("gold_answer", ""))
    if base["answerability"] == "false":
        gold_answer = ""
    if groups and not gold_answer:
        gold_answer = " ".join(group["evidence_span"] for group in groups)
    row = {
        "retrieval_dev_schema_version": SCHEMA_VERSION,
        "question": seed.get("question", base["question"]),
        "intent": seed.get("intent", base.get("intent", "fact_lookup")),
        "answerability": base["answerability"],
        "query_kind": query_kind,
        "time_scope": seed.get(
            "time_scope",
            "historical" if query_kind == "historical_control" else "current",
        ),
        "as_of": seed.get("as_of", base.get("as_of_date")),
        "query_policy": _query_policy(seed, query_kind, target_documents, target_chunks),
        "source_ids": source_ids,
        "target_statuses": target_statuses,
        "gold_document_ids": document_ids,
        "gold_chunk_ids": chunk_ids,
        "evidence_groups": groups,
        "required_evidence_group_count": len(groups),
        "gold_answer": gold_answer,
        "difficulty": seed.get("difficulty", base.get("difficulty", "medium")),
        "failure_focus": seed.get(
            "failure_focus", base.get("failure_focus", "retrieval_expected_hit")
        ),
        "provenance": base["provenance"],
        "review_status": base["review_status"],
        "training_allowed": False,
        "final_benchmark_eligible": False,
    }
    stable_payload = dict(row)
    row["dev_id"] = "retrieval_dev_sha256_" + sha256_bytes(canonical_json_bytes(stable_payload))
    return row


def build_dev_rows(
    seeds: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    legacy_sources: dict[str, tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    chunk_index = _row_index(chunks, "chunk_id", "chunk_id")
    document_index = _row_index(documents, "document_id", "document_id")
    legacy_indexes = {
        role: (path, _row_index(rows, "eval_id", f"{role} eval_id"))
        for role, (path, rows) in legacy_sources.items()
    }
    seed_ids: set[str] = set()
    output: list[dict[str, Any]] = []
    for seed in seeds:
        seed_id = seed["seed_id"]
        if seed_id in seed_ids:
            raise RuntimeError(f"duplicate seed_id: {seed_id}")
        seed_ids.add(seed_id)
        if seed["kind"] == "legacy_ref":
            role = seed["source_role"]
            if role not in legacy_indexes:
                raise RuntimeError(f"unknown legacy source role: {role}")
            source_path, source_index = legacy_indexes[role]
            source_row_id = seed["source_row_id"]
            if source_row_id not in source_index:
                raise RuntimeError(f"unknown legacy row: {role}/{source_row_id}")
            source_row = source_index[source_row_id]
            if source_row["answerability"] == "false":
                groups: list[dict[str, Any]] = []
            else:
                groups = [
                    _evidence_group(
                        1,
                        source_row["evidence_span"],
                        _matching_chunks(source_row["evidence_span"], chunks),
                    )
                ]
            base = dict(source_row)
            base["provenance"] = {
                "kind": "legacy_ref",
                "source_role": role,
                "source_path": source_path,
                "source_row_id": source_row_id,
                "seed_id": seed_id,
            }
            base["review_status"] = {
                "human_partial": "human_reviewed_existing_dev",
                "fresh": "existing_adaptive_dev",
                "domain": "existing_dev",
                "official": "existing_dev",
            }[role]
        elif seed["kind"] == "direct":
            groups = _direct_groups(seed, chunk_index)
            base = {
                "question": seed["question"],
                "intent": seed["intent"],
                "answerability": seed["answerability"],
                "gold_answer": seed.get("gold_answer", ""),
                "difficulty": seed.get("difficulty", "medium"),
                "failure_focus": seed.get("failure_focus", "retrieval_expected_hit"),
                "provenance": {
                    "kind": "direct_v3_grounding",
                    "source_role": "v3_chunk_corpus",
                    "source_path": seed.get("source_path", "data/v3/chunks"),
                    "source_row_id": None,
                    "seed_id": seed_id,
                },
                "review_status": seed.get("review_status", "agent_grounded_review"),
            }
        else:
            raise RuntimeError(f"unknown seed kind for {seed_id}: {seed['kind']}")
        output.append(
            _build_output_row(seed, base, groups, chunk_index, document_index)
        )
    return sorted(output, key=lambda row: row["dev_id"])


def audit_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    questions = [normalize_text(row["question"]) for row in rows]
    dev_ids = [row["dev_id"] for row in rows]
    answerable = [row for row in rows if row["answerability"] != "false"]
    false_rows = [row for row in rows if row["answerability"] == "false"]
    source_counts = Counter(source_id for row in rows for source_id in row["source_ids"])
    status_counts = Counter(status for row in rows for status in row["target_statuses"])
    answerability_counts = Counter(row["answerability"] for row in rows)
    query_kind_counts = Counter(row["query_kind"] for row in rows)
    review_counts = Counter(row["review_status"] for row in rows)
    gates = {
        "row_count_63": len(rows) == EXPECTED_ROW_COUNT,
        "duplicate_question_0": len(questions) == len(set(questions)),
        "duplicate_dev_id_0": len(dev_ids) == len(set(dev_ids)),
        "answerable_without_evidence_0": all(
            row["evidence_groups"] and row["gold_chunk_ids"] and row["gold_answer"]
            for row in answerable
        ),
        "false_with_gold_0": all(
            not row["evidence_groups"]
            and not row["gold_chunk_ids"]
            and not row["gold_document_ids"]
            and not row["gold_answer"]
            for row in false_rows
        ),
        "all_source_ids_represented": set(source_counts) == EXPECTED_SOURCE_IDS,
        "required_status_controls_present": {"current", "expired", "superseded", "unknown"}.issubset(status_counts),
        "required_query_kinds_present": {
            "single_fact",
            "partial",
            "unanswerable",
            "historical_control",
            "preview_control",
            "multi_evidence",
        }.issubset(query_kind_counts),
        "training_leak_0": not any(row["training_allowed"] for row in rows),
        "final_benchmark_leak_0": not any(row["final_benchmark_eligible"] for row in rows),
    }
    return {
        "row_count": len(rows),
        "answerability_counts": dict(sorted(answerability_counts.items())),
        "query_kind_counts": dict(sorted(query_kind_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "review_status_counts": dict(sorted(review_counts.items())),
        "nondefault_policy_count": sum(
            not row["query_policy"]["default_exposure_only"] for row in rows
        ),
        "multi_evidence_count": query_kind_counts["multi_evidence"],
        "gates": gates,
        "gate_pass": all(gates.values()),
    }


def _report_markdown(report: dict[str, Any]) -> str:
    audit = report["audit"]
    sources = "\n".join(
        f"| {source_id} | {count} |" for source_id, count in audit["source_counts"].items()
    )
    gates = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in audit["gates"].items()
    )
    return f"""# v3 Retrieval Dev Set Freeze

## Decision

- Retrieval A/B entry: **{report['decision']['retrieval_ab_entry']}**
- Hybrid promotion: **{report['decision']['hybrid_promotion']}**
- Final benchmark readiness: **{report['decision']['final_benchmark']}**
- This artifact is development-only and must not be used for training.

## Frozen artifacts

- Dev set: `{report['artifacts']['dev_set_path']}`
- Dev set SHA-256: `{report['artifacts']['dev_set_sha256']}`
- Manifest: `{report['artifacts']['manifest_path']}`
- Manifest SHA-256: `{report['artifacts']['manifest_sha256']}`

## Composition

- Rows: {audit['row_count']}
- Answerability: `{json.dumps(audit['answerability_counts'], ensure_ascii=False, sort_keys=True)}`
- Query kinds: `{json.dumps(audit['query_kind_counts'], ensure_ascii=False, sort_keys=True)}`
- Non-default policy controls: {audit['nondefault_policy_count']}
- Multi-evidence rows: {audit['multi_evidence_count']}

| source_id | rows containing source |
|---|---:|
{sources}

## Gates

{gates}

Retrieval scores, hybrid weights, Router behavior, answer generation, and final blind performance were not measured in this cycle.
"""


def build_and_freeze(
    root: Path,
    seed_spec_path: Path,
    chunks_path: Path,
    documents_path: Path,
    legacy_paths: dict[str, Path],
) -> dict[str, Any]:
    seeds = read_jsonl(seed_spec_path)
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    legacy_sources = {
        role: (path.relative_to(root).as_posix(), read_jsonl(path))
        for role, path in legacy_paths.items()
    }
    rows = build_dev_rows(seeds, chunks, documents, legacy_sources)
    audit = audit_rows(rows)
    if not audit["gate_pass"]:
        failed = [name for name, passed in audit["gates"].items() if not passed]
        raise RuntimeError(f"retrieval dev gates failed: {failed}")

    evaluation_dir = root / "data" / "v3" / "evaluation"
    reports_dir = root / "reports" / "v3"
    dev_path, dev_sha = freeze_jsonl(evaluation_dir, "retrieval_dev_v3.1", rows)
    inputs = {
        "seed_spec": {
            "path": seed_spec_path.relative_to(root).as_posix(),
            "sha256": sha256_file(seed_spec_path),
        },
        "chunks": {
            "path": chunks_path.relative_to(root).as_posix(),
            "sha256": sha256_file(chunks_path),
        },
        "documents": {
            "path": documents_path.relative_to(root).as_posix(),
            "sha256": sha256_file(documents_path),
        },
        "legacy_sources": {
            role: {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
            for role, path in sorted(legacy_paths.items())
        },
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": inputs,
        "dev_set": {
            "path": dev_path.relative_to(root).as_posix(),
            "sha256": dev_sha,
            "row_count": len(rows),
        },
        "audit": audit,
        "training_allowed": False,
        "final_benchmark_eligible": False,
    }
    manifest_path, manifest_sha = freeze_json(
        evaluation_dir, "retrieval_dev_manifest", manifest
    )
    report = {
        "report_version": "retrieval-dev-freeze-report-v3.1",
        "builder_version": BUILDER_VERSION,
        "decision": {
            "retrieval_ab_entry": "GO",
            "hybrid_promotion": "NOT_RUN",
            "final_benchmark": "NO-GO",
        },
        "audit": audit,
        "artifacts": {
            "dev_set_path": dev_path.relative_to(root).as_posix(),
            "dev_set_sha256": dev_sha,
            "manifest_path": manifest_path.relative_to(root).as_posix(),
            "manifest_sha256": manifest_sha,
        },
        "not_measured": [
            "bm25_dev_metrics",
            "dense_dev_metrics",
            "hybrid_weight_selection",
            "router_behavior",
            "generation_quality",
            "final_blind_performance",
        ],
    }
    report_json_path, report_json_sha = freeze_json(
        reports_dir, "retrieval_dev_set", report
    )
    report_md_path, report_md_sha = freeze_markdown(
        reports_dir, "retrieval_dev_set", _report_markdown(report)
    )
    return {
        "dev_set": str(dev_path),
        "dev_set_sha256": dev_sha,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_json": str(report_json_path),
        "report_json_sha256": report_json_sha,
        "report_markdown": str(report_md_path),
        "report_markdown_sha256": report_md_sha,
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build and freeze the v3 retrieval dev set")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--seed-spec", type=Path, required=True)
    parser.add_argument(
        "--chunks",
        type=Path,
        default=root / "data/v3/chunks/chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl",
    )
    parser.add_argument(
        "--documents",
        type=Path,
        default=root / "data/v3/normalized/documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl",
    )
    parser.add_argument("--domain", type=Path, default=root / "data/processed/domain_eval_set_expanded.jsonl")
    parser.add_argument("--fresh", type=Path, default=root / "data/processed/fresh_paraphrase_eval_set.jsonl")
    parser.add_argument("--human-partial", type=Path, default=root / "data/processed/partial_dev_human_v1.jsonl")
    parser.add_argument("--official", type=Path, default=root / "data/processed/official_eval_set.jsonl")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.seed_spec.resolve(),
        args.chunks.resolve(),
        args.documents.resolve(),
        {
            "domain": args.domain.resolve(),
            "fresh": args.fresh.resolve(),
            "human_partial": args.human_partial.resolve(),
            "official": args.official.resolve(),
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
