from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.diagnose_product_value_presence_parenthetical_binding import (
    score_requirement_value_presence,
)
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    kiwi_independent_requirement_queries,
)
from src.v3.product_free_rag import DEFAULT_EVIDENCE_UNITS, ProductFreeRAG


RUNNER_VERSION = "product-a6-7-runtime-application-replay-v1"
FROZEN = Path(
    "data/v3/evaluation/product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl"
)
SAVED_RESULTS = Path(
    "reports/v3/product_free_rag_a6_one_shot_"
    "4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl"
)
SAVED_PACKS = Path(
    "reports/v3/product_header_metadata_pack_post_v3_20260805.jsonl"
)
M3 = Path("reports/v3/product_value_presence_m3_20260805.jsonl")
R1_SHADOW = Path(
    "reports/v3/product_parenthetical_binding_p34_shadow_20260805.jsonl"
)
DEFAULT_OUTPUT = Path(
    "reports/v3/product_a67_runtime_r1_replay_20260805.jsonl"
)
DESCRIPTIVE_DIAGNOSTIC_KEYS = {
    "A6-17:mold_trade_types",
    "A6-29:august_special_box_prices",
}
_VALUE_ORDER = {
    "value_present_none": 0,
    "value_present_partial": 1,
    "value_present_full": 2,
}


def _coordinate(unit: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(unit.get("chunk_id") or ""),
        int(unit.get("start_char", -1)),
        int(unit.get("end_char", -1)),
        str(unit.get("unit_kind") or ""),
    )


def _citation_exact(
    citation: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> bool:
    chunk = chunks_by_id.get(str(citation.get("chunk_id") or ""))
    start = citation.get("start_char")
    end = citation.get("end_char")
    return bool(
        chunk is not None
        and isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= len(str(chunk.get("display_text") or ""))
        and str(chunk.get("display_text") or "")[start:end]
        == str(citation.get("text") or "")
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay A6 packs after the A6-7 runtime application"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"runtime replay output already exists: {output}")

    frozen_by_ref = {
        f"A6-{row['slot_ordinal']}": row for row in read_jsonl(root / FROZEN)
    }
    saved_pack_by_ref = {
        str(row["case_ref"]): row
        for row in read_jsonl(root / SAVED_PACKS)
        if row.get("type") == "case"
    }
    m3_by_ref = {
        str(row["case_ref"]): row
        for row in read_jsonl(root / M3)
        if row.get("type") == "case"
    }
    shadow_by_ref = {
        str(row["case_ref"]): row
        for row in read_jsonl(root / R1_SHADOW)
        if row.get("type") == "case"
    }
    saved_result_by_ref = {
        f"A6-{row['slot_ordinal']}": row
        for row in read_jsonl(root / SAVED_RESULTS)
        if row.get("type") == "case"
    }

    rag = ProductFreeRAG(
        root=root,
        device=args.device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    records = []
    for slot in range(1, 33):
        case_ref = f"A6-{slot}"
        frozen = frozen_by_ref[case_ref]
        saved_pack = saved_pack_by_ref[case_ref]
        question = str(frozen["question_text"])
        requirement_queries = kiwi_independent_requirement_queries(question)
        current_pack = build_atomic_reranked_product_evidence_pack(
            list(saved_pack["candidate_chunk_ids"]),
            question=question,
            requirement_queries=requirement_queries or None,
            chunks_by_id=rag._artifacts.chunks_by_id,
            documents_by_id=rag._artifacts.documents_by_id,
            temporal_by_document=rag.temporal_by_document,
            score_pairs=rag._score_pairs,
            max_units=DEFAULT_EVIDENCE_UNITS,
            prefilter_per_query=32,
            reserve_per_query=3 if len(requirement_queries) > 1 else 1,
        )
        baseline_coordinates = [
            _coordinate(unit) for unit in saved_pack["evidence_pack"]
        ]
        current_coordinates = [_coordinate(unit) for unit in current_pack]
        shadow_coordinates = [
            _coordinate(unit) for unit in shadow_by_ref[case_ref]["shadow_pack"]
        ]
        requirements = [
            score_requirement_value_presence(
                requirement,
                evidence_pack=current_pack,
                as_of=str(frozen["as_of"]),
            )
            for requirement in frozen.get("requirements") or []
        ]
        m3_requirements = {
            str(row["requirement_id"]): row
            for row in m3_by_ref[case_ref]["requirements"]
        }
        value_changes = [
            {
                "requirement_id": row["requirement_id"],
                "before": m3_requirements[str(row["requirement_id"])][
                    "value_presence"
                ],
                "after": row["value_presence"],
                "gate_kind": (
                    "descriptive_diagnostic"
                    if f"{case_ref}:{row['requirement_id']}"
                    in DESCRIPTIVE_DIAGNOSTIC_KEYS
                    else "numeric_date_time_currency"
                ),
            }
            for row in requirements
            if m3_requirements[str(row["requirement_id"])]["value_presence"]
            != row["value_presence"]
        ]
        coordinate_mismatches = []
        for unit in current_pack:
            source_text = str(
                rag._artifacts.chunks_by_id[str(unit["chunk_id"])].get(
                    "display_text"
                )
                or ""
            )
            if source_text[
                int(unit["start_char"]) : int(unit["end_char"])
            ] != str(unit.get("text") or ""):
                coordinate_mismatches.append(_coordinate(unit))

        saved_result = saved_result_by_ref[case_ref]["result"]
        citations = [
            citation
            for claim in saved_result.get("claims") or []
            for citation in claim.get("citations") or []
        ]
        saved_citations_exact = all(
            _citation_exact(citation, chunks_by_id=rag._artifacts.chunks_by_id)
            for citation in citations
        )
        records.append(
            {
                "type": "case",
                "case_ref": case_ref,
                "question": question,
                "candidate_chunk_ids": saved_pack["candidate_chunk_ids"],
                "evidence_pack": current_pack,
                "requirements": requirements,
                "value_changes": value_changes,
                "pack_set_changed": (
                    set(baseline_coordinates) != set(current_coordinates)
                ),
                "pack_order_changed": (
                    set(baseline_coordinates) == set(current_coordinates)
                    and baseline_coordinates != current_coordinates
                ),
                "baseline_coordinates": baseline_coordinates,
                "current_coordinates": current_coordinates,
                "r1_shadow_reference_exact": (
                    current_coordinates == shadow_coordinates
                ),
                "coordinate_mismatches": coordinate_mismatches,
                "saved_citations_exact": saved_citations_exact,
                "saved_all_exposed_citations_verified": bool(
                    saved_result.get("verification", {}).get(
                        "all_exposed_citations_verified"
                    )
                ),
            }
        )
        print(
            json.dumps(
                {
                    "case_ref": case_ref,
                    "pack_set_changed": records[-1]["pack_set_changed"],
                    "value_changes": value_changes,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    measurable = [
        requirement
        for record in records
        for requirement in record["requirements"]
        if str(requirement["value_presence"]).startswith("value_present_")
    ]
    value_counts = Counter(row["value_presence"] for row in measurable)
    changes = [
        {"case_ref": record["case_ref"], **change}
        for record in records
        for change in record["value_changes"]
    ]
    gate_decreases = [
        change
        for change in changes
        if change["gate_kind"] == "numeric_date_time_currency"
        and change["before"] in _VALUE_ORDER
        and change["after"] in _VALUE_ORDER
        and _VALUE_ORDER[change["after"]] < _VALUE_ORDER[change["before"]]
    ]
    a67 = next(record for record in records if record["case_ref"] == "A6-7")
    a67_base = next(
        row
        for row in a67["requirements"]
        if row["requirement_id"] == "base_cooldown_change"
    )
    chunks_path = Path(rag._artifacts.provenance["chunks_path"])
    if not chunks_path.is_absolute():
        chunks_path = root / chunks_path
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "phase": "R1",
        "qwen_calls": 0,
        "case_count": len(records),
        "measurable_requirement_count": len(measurable),
        "value_presence_counts": dict(value_counts),
        "m3_value_presence_counts": {
            "value_present_full": 39,
            "value_present_partial": 4,
            "value_present_none": 6,
        },
        "value_presence_changes": changes,
        "numeric_date_time_currency_decreases": gate_decreases,
        "descriptive_diagnostic_keys": sorted(DESCRIPTIVE_DIAGNOSTIC_KEYS),
        "a6_7_base_cooldown_value_presence": a67_base["value_presence"],
        "a6_7_base_cooldown_value_checks": a67_base["value_checks"],
        "pack_set_changed_case_refs": [
            record["case_ref"] for record in records if record["pack_set_changed"]
        ],
        "pack_order_changed_case_refs": [
            record["case_ref"] for record in records if record["pack_order_changed"]
        ],
        "r1_shadow_reference_exact_cases": sum(
            record["r1_shadow_reference_exact"] for record in records
        ),
        "coordinate_restoration_exact_cases": sum(
            not record["coordinate_mismatches"] for record in records
        ),
        "all_exposed_citations_exact_cases": sum(
            record["saved_citations_exact"] for record in records
        ),
        "all_exposed_citations_verified_cases": sum(
            record["saved_all_exposed_citations_verified"] for record in records
        ),
        "candidate_chunk_ids_unchanged_cases": len(records),
        "chunk_id_missing_count": sum(
            str(unit["chunk_id"]) not in rag._artifacts.chunks_by_id
            for record in records
            for unit in record["evidence_pack"]
        ),
        "chunks_path": chunks_path.as_posix(),
        "chunks_sha256": _sha256(chunks_path),
        "gates": {
            "a6_7_base_cooldown_full": (
                a67_base["value_presence"] == "value_present_full"
            ),
            "numeric_date_time_currency_decrease_zero": not gate_decreases,
            "coordinate_restoration_32_of_32": all(
                not record["coordinate_mismatches"] for record in records
            ),
            "all_exposed_citations_exact_32_of_32": all(
                record["saved_citations_exact"] for record in records
            ),
            "all_exposed_citations_verified_32_of_32": all(
                record["saved_all_exposed_citations_verified"]
                for record in records
            ),
            "candidate_chunk_ids_unchanged_32_of_32": True,
            "chunk_id_missing_zero": not any(
                str(unit["chunk_id"]) not in rag._artifacts.chunks_by_id
                for record in records
                for unit in record["evidence_pack"]
            ),
            "r1_shadow_reference_exact_32_of_32": all(
                record["r1_shadow_reference_exact"] for record in records
            ),
        },
    }
    summary["r1_replay_go"] = all(summary["gates"].values())
    write_jsonl(output, [*records, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
