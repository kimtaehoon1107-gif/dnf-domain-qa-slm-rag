from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "entailment-natural-review-builder-v3.1.1"
PACKET_SCHEMA_VERSION = "entailment-natural-review-item-v3.1"
LEDGER_SCHEMA_VERSION = "entailment-natural-sampling-ledger-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-natural-review-manifest-v3.1"
REPORT_SCHEMA_VERSION = "entailment-natural-review-report-v3.1"
ITEMS_PER_SOURCE_PER_PRIMARY_STRATUM = 2
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
DEFAULT_RERANKER_SCORES = Path(
    "data/v3/evidence/"
    "evidence_reranker_scores_ee3580ff687edfe2ade16a6e55391859a46ee9bf7c50b8afd3f9065892607d29.jsonl"
)
DEFAULT_RERANKER_MANIFEST = Path(
    "data/v3/evidence/"
    "evidence_reranker_manifest_ad6b3f074d8f6edf848c0129d0ea3d8de1c9438aa3de98dde0bfac0fb7a2f26c.json"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_BM25_INDEX = Path(
    "data/v3/indexes/"
    "bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
DEFAULT_BM25_MANIFEST = Path(
    "data/v3/indexes/"
    "bm25_manifest_f963e4e6a8bd64540ec030cdd3a4e881cd4034d833655dc624b838cafae8dbea.json"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/prepare_entailment_review.py")
DEFAULT_BM25_SOURCE = Path("src/v3/build_bm25.py")

HISTORICAL_QUOTAS = {
    "dnf_account_policy": 2,
    "dnf_game_guide": 1,
    "dnf_monthly_item": 2,
    "dnf_seria_shop": 2,
    "dnf_update": 1,
}
HISTORICAL_STATUSES = {
    "dnf_account_policy": ("superseded",),
    "dnf_game_guide": ("superseded",),
    "dnf_monthly_item": ("expired",),
    "dnf_seria_shop": ("expired",),
    "dnf_update": ("unknown",),
}
REVIEW_FIELDS = {
    "review_label",
    "reviewer_type",
    "reviewer_id",
    "reviewed_at",
    "decisive_excerpt",
    "review_rationale",
    "needs_adjudication",
}
RESERVED_REVIEWER_IDS = {"agent", "ai", "codex", "llm", "model", "openai"}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _item_id(dev_id: str, chunk_id: str, claim_text: str) -> str:
    payload = {"dev_id": dev_id, "chunk_id": chunk_id, "claim_text": claim_text}
    return "entailment_review_sha256_" + _sha256_bytes(_canonical_json_bytes(payload))


def _acceptable_chunk_ids(dev: dict[str, Any]) -> set[str]:
    return {
        chunk_id
        for group in dev["evidence_groups"]
        for chunk_id in group["acceptable_chunk_ids"]
    }


def select_seed_rows(dev_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    selected = {}
    for source_id in SOURCE_IDS:
        candidates = sorted(
            (
                row
                for row in dev_rows
                if row["answerability"] == "true"
                and row["query_kind"] == "single_fact"
                and row["source_ids"] == [source_id]
                and bool(row["gold_answer"].strip())
            ),
            key=lambda row: row["dev_id"],
        )
        if len(candidates) < ITEMS_PER_SOURCE_PER_PRIMARY_STRATUM:
            raise RuntimeError(f"Not enough natural review seeds for {source_id}")
        selected[source_id] = candidates[:ITEMS_PER_SOURCE_PER_PRIMARY_STRATUM]
    return selected


def _selection(
    dev: dict[str, Any],
    chunk_id: str,
    stratum: str,
    *,
    retrieval_rank: int | None = None,
    reranker_score: float | None = None,
    bm25_score: float | None = None,
) -> dict[str, Any]:
    return {
        "dev": dev,
        "chunk_id": chunk_id,
        "stratum": stratum,
        "retrieval_rank": retrieval_rank,
        "reranker_score": reranker_score,
        "bm25_score": bm25_score,
    }


def select_samples(
    dev_rows: list[dict[str, Any]],
    reranker_rows: list[dict[str, Any]],
    bm25_index: dict[str, Any],
) -> list[dict[str, Any]]:
    seeds = select_seed_rows(dev_rows)
    reranker_by_id = {row["dev_id"]: row for row in reranker_rows}
    if len(reranker_by_id) != len(reranker_rows):
        raise RuntimeError("Duplicate reranker dev_id")
    selections = []
    for source_id in SOURCE_IDS:
        for dev in seeds[source_id]:
            acceptable_ids = _acceptable_chunk_ids(dev)
            selections.append(
                _selection(dev, sorted(acceptable_ids)[0], "annotated_anchor")
            )
            reranker = reranker_by_id.get(dev["dev_id"])
            if reranker is None:
                raise RuntimeError(f"Missing reranker row: {dev['dev_id']}")
            candidates = sorted(
                (
                    row
                    for row in reranker["candidates"]
                    if row["chunk_id"] not in acceptable_ids
                ),
                key=lambda row: (
                    -float(row["reranker_score"]),
                    int(row["retrieval_rank"]),
                    row["chunk_id"],
                ),
            )
            if not candidates:
                raise RuntimeError(f"No current hard candidate: {dev['dev_id']}")
            candidate = candidates[0]
            selections.append(
                _selection(
                    dev,
                    candidate["chunk_id"],
                    "default_hard_candidate",
                    retrieval_rank=candidate["retrieval_rank"],
                    reranker_score=round(float(candidate["reranker_score"]), 8),
                )
            )

    for source_id, quota in HISTORICAL_QUOTAS.items():
        for dev in seeds[source_id][:quota]:
            hits = search_bm25(
                bm25_index,
                f"{dev['question']} {dev['gold_answer']}",
                top_k=5,
                policy=SearchPolicy(
                    default_exposure_only=False,
                    allowed_statuses=HISTORICAL_STATUSES[source_id],
                    include_review_required=False,
                    source_ids=(source_id,),
                ),
            )
            if not hits:
                raise RuntimeError(f"No historical review candidate: {dev['dev_id']}")
            hit = hits[0]
            selections.append(
                _selection(
                    dev,
                    hit["chunk_id"],
                    "historical_revision_candidate",
                    retrieval_rank=hit["rank"],
                    bm25_score=round(float(hit["score"]), 8),
                )
            )
    pairs = [(row["dev"]["dev_id"], row["chunk_id"]) for row in selections]
    if len(pairs) != len(set(pairs)):
        raise RuntimeError("Duplicate dev/chunk pair in natural review selection")
    return selections


def build_packet_and_ledger(
    dev_rows: list[dict[str, Any]],
    reranker_rows: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    bm25_index: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    documents_by_id = {row["document_id"]: row for row in documents}
    if len(chunks_by_id) != len(chunks) or len(documents_by_id) != len(documents):
        raise RuntimeError("Duplicate ChunkV3 or DocumentV3 ID")
    raw_rows = []
    for selected in select_samples(dev_rows, reranker_rows, bm25_index):
        dev = selected["dev"]
        chunk = chunks_by_id.get(selected["chunk_id"])
        if chunk is None:
            raise RuntimeError(f"Unknown selected chunk: {selected['chunk_id']}")
        document = documents_by_id.get(chunk["parent_document_id"])
        if document is None:
            raise RuntimeError(f"Unknown selected document: {chunk['parent_document_id']}")
        item_id = _item_id(dev["dev_id"], chunk["chunk_id"], dev["gold_answer"])
        packet = {
            "review_item_schema_version": PACKET_SCHEMA_VERSION,
            "item_id": item_id,
            "item_ordinal": None,
            "question": dev["question"],
            "claim_text": dev["gold_answer"],
            "claim_as_of": dev["as_of"],
            "claim_time_scope": dev["time_scope"],
            "evidence_chunk_id": chunk["chunk_id"],
            "evidence_document_id": chunk["parent_document_id"],
            "evidence_title": document["title"],
            "evidence_url": document["canonical_url"],
            "evidence_source_id": chunk["source_id"],
            "evidence_status": chunk["status"],
            "evidence_valid_from": chunk["valid_from"],
            "evidence_valid_to": chunk["valid_to"],
            "evidence_text": chunk["display_text"],
            "review_label": None,
            "reviewer_type": None,
            "reviewer_id": None,
            "reviewed_at": None,
            "decisive_excerpt": None,
            "review_rationale": None,
            "needs_adjudication": None,
            "training_allowed": False,
            "final_benchmark_eligible": False,
        }
        ledger = {
            "sampling_ledger_schema_version": LEDGER_SCHEMA_VERSION,
            "item_id": item_id,
            "item_ordinal": None,
            "stratum": selected["stratum"],
            "claim_source_id": dev["source_ids"][0],
            "dev_id": dev["dev_id"],
            "evidence_chunk_id": chunk["chunk_id"],
            "evidence_document_id": chunk["parent_document_id"],
            "evidence_source_id": chunk["source_id"],
            "evidence_status": chunk["status"],
            "annotated_acceptable_chunk": chunk["chunk_id"]
            in _acceptable_chunk_ids(dev),
            "retrieval_rank": selected["retrieval_rank"],
            "reranker_score": selected["reranker_score"],
            "bm25_score": selected["bm25_score"],
            "model_prediction_in_review_packet": False,
            "training_allowed": False,
            "final_benchmark_eligible": False,
        }
        raw_rows.append((item_id, packet, ledger))

    packet_rows = []
    ledger_rows = []
    for ordinal, (_, packet, ledger) in enumerate(sorted(raw_rows, key=lambda row: row[0])):
        packet_rows.append({**packet, "item_ordinal": ordinal})
        ledger_rows.append({**ledger, "item_ordinal": ordinal})
    return packet_rows, ledger_rows


def audit_packet(
    packet_rows: list[dict[str, Any]], ledger_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    strata = Counter(row["stratum"] for row in ledger_rows)
    primary_by_source = Counter(
        (row["stratum"], row["claim_source_id"])
        for row in ledger_rows
        if row["stratum"] != "historical_revision_candidate"
    )
    historical_status_violations = sum(
        row["evidence_status"] not in HISTORICAL_STATUSES[row["claim_source_id"]]
        for row in ledger_rows
        if row["stratum"] == "historical_revision_candidate"
    )
    gates = {
        "packet_count_40": len(packet_rows) == 40,
        "ledger_count_40": len(ledger_rows) == 40,
        "item_ids_align": [row["item_id"] for row in packet_rows]
        == [row["item_id"] for row in ledger_rows],
        "ordinals_contiguous": [row["item_ordinal"] for row in packet_rows]
        == list(range(40)),
        "item_ids_unique": len({row["item_id"] for row in packet_rows}) == 40,
        "strata_16_16_8": strata
        == {
            "annotated_anchor": 16,
            "default_hard_candidate": 16,
            "historical_revision_candidate": 8,
        },
        "primary_source_balance_2_each": all(
            primary_by_source[(stratum, source_id)] == 2
            for stratum in ("annotated_anchor", "default_hard_candidate")
            for source_id in SOURCE_IDS
        ),
        "historical_quota_matches": all(
            sum(
                row["stratum"] == "historical_revision_candidate"
                and row["claim_source_id"] == source_id
                for row in ledger_rows
            )
            == quota
            for source_id, quota in HISTORICAL_QUOTAS.items()
        ),
        "historical_status_violations_0": historical_status_violations == 0,
        "hard_candidates_not_annotated": not any(
            row["annotated_acceptable_chunk"]
            for row in ledger_rows
            if row["stratum"] != "annotated_anchor"
        ),
        "review_labels_all_pending": all(
            row["review_label"] is None for row in packet_rows
        ),
        "model_predictions_hidden": not any(
            "prediction" in key.lower()
            for row in packet_rows
            for key in row
        ),
        "sampling_strata_hidden": not any("stratum" in row for row in packet_rows),
        "training_leak_0": not any(
            row["training_allowed"] for row in packet_rows + ledger_rows
        ),
        "final_benchmark_leak_0": not any(
            row["final_benchmark_eligible"] for row in packet_rows + ledger_rows
        ),
    }
    return {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "stratum_counts": dict(sorted(strata.items())),
        "claim_source_counts": dict(
            sorted(Counter(row["claim_source_id"] for row in ledger_rows).items())
        ),
        "evidence_status_counts": dict(
            sorted(Counter(row["evidence_status"] for row in ledger_rows).items())
        ),
    }


def _valid_reviewed_at(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def audit_completed_reviews(
    packet_rows: list[dict[str, Any]], reviewed_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    packet_by_id = {row["item_id"]: row for row in packet_rows}
    reviewed_by_id = {row.get("item_id"): row for row in reviewed_rows}
    errors = []
    if len(packet_by_id) != len(packet_rows):
        errors.append("duplicate packet item_id")
    if len(reviewed_by_id) != len(reviewed_rows):
        errors.append("duplicate reviewed item_id")
    if set(packet_by_id) != set(reviewed_by_id):
        errors.append("reviewed item IDs differ from frozen packet")
    label_counts: Counter[str] = Counter()
    adjudication_count = 0
    for item_id in sorted(set(packet_by_id) & set(reviewed_by_id)):
        packet = packet_by_id[item_id]
        reviewed = reviewed_by_id[item_id]
        if set(reviewed) != set(packet):
            errors.append(f"{item_id}: reviewed keys differ from packet schema")
            continue
        for key in set(packet) - REVIEW_FIELDS:
            if reviewed[key] != packet[key]:
                errors.append(f"{item_id}: immutable field changed: {key}")
        label = reviewed["review_label"]
        if label not in LABELS:
            errors.append(f"{item_id}: invalid review_label")
        else:
            label_counts[label] += 1
        if reviewed["reviewer_type"] != "human":
            errors.append(f"{item_id}: reviewer_type must be human")
        reviewer_id = reviewed["reviewer_id"]
        if (
            not isinstance(reviewer_id, str)
            or not reviewer_id.strip()
            or reviewer_id.strip().casefold() in RESERVED_REVIEWER_IDS
        ):
            errors.append(f"{item_id}: invalid human reviewer_id")
        if not _valid_reviewed_at(reviewed["reviewed_at"]):
            errors.append(f"{item_id}: reviewed_at needs a timezone")
        rationale = reviewed["review_rationale"]
        if not isinstance(rationale, str) or len(rationale.strip()) < 10:
            errors.append(f"{item_id}: review_rationale is too short")
        needs_adjudication = reviewed["needs_adjudication"]
        if not isinstance(needs_adjudication, bool):
            errors.append(f"{item_id}: needs_adjudication must be boolean")
        elif needs_adjudication:
            adjudication_count += 1
        excerpt = reviewed["decisive_excerpt"]
        if label in {"support", "contradiction"}:
            if not isinstance(excerpt, str) or not excerpt.strip():
                errors.append(f"{item_id}: decisive_excerpt is required")
            elif _normalized_text(excerpt) not in _normalized_text(
                reviewed["evidence_text"]
            ):
                errors.append(f"{item_id}: decisive_excerpt is not in evidence")
        elif excerpt not in {None, ""} and _normalized_text(excerpt) not in _normalized_text(
            reviewed["evidence_text"]
        ):
            errors.append(f"{item_id}: optional decisive_excerpt is not in evidence")
    gates = {
        "row_count_matches_packet": len(reviewed_rows) == len(packet_rows),
        "validation_errors_0": not errors,
        "adjudication_pending_0": adjudication_count == 0,
        "all_three_labels_present": set(label_counts) == set(LABELS),
    }
    return {
        "gates": gates,
        "primary_review_complete": gates["row_count_matches_packet"]
        and gates["validation_errors_0"],
        "ready_for_scoring": all(gates.values()),
        "label_counts": dict(sorted(label_counts.items())),
        "adjudication_pending_count": adjudication_count,
        "errors": errors,
    }


def _markdown(report: dict[str, Any]) -> str:
    audit = report["audit"]
    return f"""# DNF RAG v3 Natural Entailment Human Review Packet

## Decision

- Packet integrity: **{report['decision']['packet_integrity']}**
- Human review: **{report['decision']['human_review']}**
- Natural verifier evaluation: **{report['decision']['natural_verifier_evaluation']}**
- Production verifier: **{report['decision']['production_verifier']}**
- Generator entry: **{report['decision']['generator_entry']}**

## Composition

- total: {report['packet']['row_count']}
- annotated anchors: {audit['stratum_counts']['annotated_anchor']}
- current hard candidates: {audit['stratum_counts']['default_hard_candidate']}
- historical/preview candidates: {audit['stratum_counts']['historical_revision_candidate']}
- claim sources: {audit['claim_source_counts']}

The reviewer-facing packet hides sampling strata, dev annotations, and model predictions. The sampling ledger must not be opened during primary labeling.

## Label rules

- `support`: the evidence entails every material part of the claim for the stated time scope.
- `contradiction`: the evidence explicitly conflicts with at least one material part of the claim.
- `insufficient`: the evidence neither supports nor contradicts the claim, including omission or a different item/context.

For every row, set `reviewer_type=human`, a non-placeholder `reviewer_id`, a timezone-bearing `reviewed_at`, `review_rationale`, and `needs_adjudication`. A support or contradiction label also requires an exact `decisive_excerpt` copied from `evidence_text`.

Validate a completed copy with:

`python src/v3/prepare_entailment_review.py --validate-reviewed <completed.jsonl>`

No verifier metric may be computed until validation reports `ready_for_scoring=true`.

## Artifacts

- review packet: `{report['packet']['path']}`
- sampling ledger: `{report['sampling_ledger']['path']}`
- manifest: `{report['manifest']['path']}`
"""


def build_and_freeze(
    root: Path,
    dev_path: Path,
    reranker_scores_path: Path,
    reranker_manifest_path: Path,
    chunks_path: Path,
    documents_path: Path,
    bm25_index_path: Path,
    bm25_manifest_path: Path,
    builder_source_path: Path,
) -> dict[str, Any]:
    input_paths = {
        "retrieval_dev": dev_path,
        "reranker_scores": reranker_scores_path,
        "reranker_manifest": reranker_manifest_path,
        "chunks": chunks_path,
        "documents": documents_path,
        "bm25_index": bm25_index_path,
        "bm25_manifest": bm25_manifest_path,
        "builder_source": builder_source_path,
        "bm25_search_source": root / DEFAULT_BM25_SOURCE,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    packet, ledger = build_packet_and_ledger(
        read_jsonl(dev_path),
        read_jsonl(reranker_scores_path),
        read_jsonl(chunks_path),
        read_jsonl(documents_path),
        json.loads(bm25_index_path.read_text(encoding="utf-8")),
    )
    audit = audit_packet(packet, ledger)
    if not audit["gate_pass"]:
        raise RuntimeError("Natural entailment review packet audit failed")

    evaluation_dir = root / "data/v3/evaluation"
    reports_dir = root / "reports/v3"
    packet_bytes = _serialize_jsonl(packet, lambda row: row["item_ordinal"])
    packet_sha = _sha256_bytes(packet_bytes)
    packet_path = evaluation_dir / f"entailment_natural_review_packet_{packet_sha}.jsonl"
    write_immutable(packet_path, packet_bytes)
    ledger_bytes = _serialize_jsonl(ledger, lambda row: row["item_ordinal"])
    ledger_sha = _sha256_bytes(ledger_bytes)
    ledger_path = evaluation_dir / f"entailment_natural_sampling_ledger_{ledger_sha}.jsonl"
    write_immutable(ledger_path, ledger_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "sampling_contract": {
            "primary_seed_rule": "minimum two single_fact true dev_id per source",
            "annotated_anchor_rule": "minimum acceptable_chunk_id",
            "default_hard_rule": "highest reranker score excluding acceptable IDs",
            "historical_rule": "highest same-source BM25 hit in fixed historical statuses",
            "historical_quotas": HISTORICAL_QUOTAS,
            "historical_statuses": HISTORICAL_STATUSES,
            "review_order": "item_id ascending",
            "expected_labels_assigned": False,
        },
        "packet": {
            "path": _relative(root, packet_path),
            "sha256": packet_sha,
            "row_count": len(packet),
            "model_predictions_included": False,
            "sampling_strata_included": False,
            "human_labels_complete": False,
        },
        "sampling_ledger": {
            "path": _relative(root, ledger_path),
            "sha256": ledger_sha,
            "row_count": len(ledger),
            "reviewer_blinded": True,
        },
        "audit": audit,
        "use_restrictions": {
            "training_allowed": False,
            "final_benchmark_eligible": False,
            "scoring_allowed_before_human_validation": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evaluation_dir / f"entailment_natural_review_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "decision": {
            "packet_integrity": "GO",
            "human_review": "PENDING",
            "natural_verifier_evaluation": "NO-GO",
            "production_verifier": "NO-GO",
            "generator_entry": "NO-GO",
            "final_benchmark": "NO-GO",
        },
        "audit": audit,
        "packet": {
            "path": _relative(root, packet_path),
            "sha256": packet_sha,
            "row_count": len(packet),
        },
        "sampling_ledger": {
            "path": _relative(root, ledger_path),
            "sha256": ledger_sha,
            "row_count": len(ledger),
        },
        "manifest": {
            "path": _relative(root, manifest_path),
            "sha256": manifest_sha,
        },
        "not_measured": [
            "human_reviewed_label_distribution",
            "natural_entailment_accuracy",
            "natural_contradiction_recall",
            "natural_insufficient_recall",
            "confidence_calibration",
            "generator_integration",
            "final_blind_performance",
        ],
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = reports_dir / f"entailment_natural_review_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = reports_dir / f"entailment_natural_review_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha,
        "ledger_path": str(ledger_path),
        "ledger_sha256": ledger_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decision": report["decision"],
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Prepare v3 natural NLI human review")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--reranker-scores", type=Path, default=root / DEFAULT_RERANKER_SCORES
    )
    parser.add_argument(
        "--reranker-manifest", type=Path, default=root / DEFAULT_RERANKER_MANIFEST
    )
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--bm25-index", type=Path, default=root / DEFAULT_BM25_INDEX)
    parser.add_argument(
        "--bm25-manifest", type=Path, default=root / DEFAULT_BM25_MANIFEST
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument("--validate-reviewed", type=Path)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.validate_reviewed is not None:
        packets = sorted((args.root / "data/v3/evaluation").glob(
            "entailment_natural_review_packet_*.jsonl"
        ))
        if len(packets) != 1:
            raise RuntimeError("Expected exactly one frozen natural review packet")
        audit = audit_completed_reviews(
            read_jsonl(packets[0]), read_jsonl(args.validate_reviewed.resolve())
        )
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        if not audit["ready_for_scoring"]:
            raise RuntimeError("Completed review file is not ready for scoring")
        return
    result = build_and_freeze(
        args.root.resolve(),
        args.dev_set.resolve(),
        args.reranker_scores.resolve(),
        args.reranker_manifest.resolve(),
        args.chunks.resolve(),
        args.documents.resolve(),
        args.bm25_index.resolve(),
        args.bm25_manifest.resolve(),
        args.builder_source.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
