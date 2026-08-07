from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3 import product_evidence_pack
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    kiwi_independent_requirement_queries,
)
from src.v3.product_free_rag import (
    DEFAULT_EVIDENCE_UNITS,
    ProductFreeRAG,
    expand_evidence_candidate_chunk_ids,
)


DEFAULT_OUTPUT = Path(
    "reports/v3/product_table_subject_binding_s2_20260805.jsonl"
)
PRE_A6 = Path("reports/v3/product_header_metadata_pack_post_v3_20260805.jsonl")
POST_A6 = Path(
    "reports/v3/product_table_subject_binding_a6_post_decoupled_20260805.jsonl"
)
RUNNER_VERSION = "product-table-subject-binding-s2-v1"
_INTRODUCER_MARKER = " > 표 도입: "
_SUBJECT_MARKER = " > 표 대상: "


def _jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                row["_line_number"] = line_number
                yield row


def _without_table_introducer_context(context: str) -> str:
    start = context.find(_INTRODUCER_MARKER)
    if start < 0:
        return context
    subject_start = context.find(_SUBJECT_MARKER, start)
    if subject_start < 0:
        return context[:start]
    return context[:start] + context[subject_start:]


def _legacy_chunk_atomic_units(*args, **kwargs) -> list[dict[str, Any]]:
    units = _legacy_chunk_atomic_units.current(*args, **kwargs)
    return [
        {
            **unit,
            "context_text": _without_table_introducer_context(
                str(unit.get("context_text") or "")
            ),
        }
        for unit in units
    ]


_legacy_chunk_atomic_units.current = product_evidence_pack._chunk_atomic_units


def _coordinate(unit: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(unit.get("chunk_id") or ""),
        int(unit.get("start_char", -1)),
        int(unit.get("end_char", -1)),
        str(unit.get("unit_kind") or ""),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _a6_comparison(root: Path) -> dict[str, Any]:
    pre_rows = {
        row["case_ref"]: row
        for row in read_jsonl(root / PRE_A6)
        if row.get("type") == "case"
    }
    post_rows = {
        row["case_ref"]: row
        for row in read_jsonl(root / POST_A6)
        if row.get("type") == "case"
    }
    changed_sets = []
    changed_order = []
    changed_context = []
    for case_ref, pre in pre_rows.items():
        post = post_rows[case_ref]
        pre_coordinates = [_coordinate(unit) for unit in pre["evidence_pack"]]
        post_coordinates = [_coordinate(unit) for unit in post["evidence_pack"]]
        if set(pre_coordinates) != set(post_coordinates):
            changed_sets.append(case_ref)
        elif pre_coordinates != post_coordinates:
            changed_order.append(case_ref)
        pre_context = {
            _coordinate(unit): str(unit.get("context_text") or "")
            for unit in pre["evidence_pack"]
        }
        if any(
            coordinate in pre_context
            and pre_context[coordinate] != str(unit.get("context_text") or "")
            for unit in post["evidence_pack"]
            for coordinate in [_coordinate(unit)]
        ):
            changed_context.append(case_ref)
    pre_summary = next(
        row for row in read_jsonl(root / PRE_A6) if row.get("type") == "summary"
    )
    post_summary = next(
        row for row in read_jsonl(root / POST_A6) if row.get("type") == "summary"
    )
    a67_post = post_rows["A6-7"]["evidence_pack"]
    return {
        "gold_visibility_unchanged": (
            pre_summary["gold_visibility"] == post_summary["gold_visibility"]
        ),
        "gold_visible_before": pre_summary["gold_visible_count"],
        "gold_visible_after": post_summary["gold_visible_count"],
        "pack_set_changed_case_refs": changed_sets,
        "pack_order_only_changed_case_refs": changed_order,
        "context_changed_case_refs": changed_context,
        "a6_1_pack_set_changed": "A6-1" in changed_sets,
        "a6_7_has_gale_introducer": any(
            "표 도입: - '질풍' 스킬 개화 옵션이 변경됩니다."
            in str(unit.get("context_text") or "")
            for unit in a67_post
        ),
        "coordinate_restoration_exact_cases": post_summary.get(
            "coordinate_restoration_exact_cases"
        ),
        "chunk_sha_changed": (
            pre_summary["chunks_sha256"] != post_summary["chunks_sha256"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay saved candidate sets before/after table introducers"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")

    source_paths = sorted(
        {
            *root.glob("reports/v3/**/*.jsonl"),
            *root.glob("outputs/v3/**/*.jsonl"),
        }
    )
    cases_by_key: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    table_citation_record_count = 0
    saved_record_count = 0
    for path in source_paths:
        if path.resolve() == output.resolve() or path.name.startswith(
            "product_table_subject_binding"
        ):
            continue
        for source_row in _jsonl_rows(path):
            result = source_row.get("result")
            if not isinstance(result, dict) or not result.get("candidates"):
                continue
            question = str(
                source_row.get("question") or result.get("question") or ""
            ).strip()
            if not question:
                continue
            candidate_ids = tuple(
                str(candidate.get("chunk_id") or "")
                for candidate in result["candidates"]
                if isinstance(candidate, dict) and candidate.get("chunk_id")
            )
            if not candidate_ids:
                continue
            saved_record_count += 1
            citations = [
                citation
                for claim in result.get("claims") or []
                for citation in claim.get("citations") or []
                if isinstance(citation, dict)
            ]
            uses_table_citation = any(
                str(citation.get("text") or "").strip().startswith("|")
                and str(citation.get("text") or "").strip().endswith("|")
                for citation in citations
            )
            table_citation_record_count += uses_table_citation
            key = (question, candidate_ids)
            case = cases_by_key.setdefault(
                key,
                {
                    "question": question,
                    "candidate_chunk_ids": list(candidate_ids),
                    "source_records": [],
                },
            )
            case["source_records"].append(
                {
                    "source_path": path.relative_to(root).as_posix(),
                    "source_line": source_row["_line_number"],
                    "slot": source_row.get(
                        "slot_ordinal", source_row.get("slot")
                    ),
                    "uses_table_citation": uses_table_citation,
                }
            )

    rag = ProductFreeRAG(
        root=root,
        device=args.device,
        use_identity_shortlist=True,
        use_compact_evidence_pack=True,
        use_atomic_evidence_reranker=True,
    )
    rag._initialize()
    chunks_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in rag._artifacts.chunks_by_id.values():
        chunks_by_parent[str(chunk["parent_document_id"])].append(chunk)

    new_chunk_atomic_units = product_evidence_pack._chunk_atomic_units
    score_cache: dict[tuple[str, str], float] = {}
    scorer_calls = 0

    def cached_score_pairs(
        pairs: list[tuple[str, str]],
    ) -> list[float]:
        nonlocal scorer_calls
        missing = list(
            dict.fromkeys(pair for pair in pairs if pair not in score_cache)
        )
        if missing:
            scores = list(rag._score_pairs(missing))
            if len(scores) != len(missing):
                raise RuntimeError("cached atomic score count mismatch")
            score_cache.update(zip(missing, scores))
            scorer_calls += 1
        return [score_cache[pair] for pair in pairs]

    rows = []
    context_changed_records = 0
    pack_set_changed_records = 0
    pack_order_changed_records = 0
    coordinate_mismatch_records = 0
    for index, case in enumerate(cases_by_key.values(), 1):
        question = case["question"]
        selected = [
            {
                "chunk_id": chunk_id,
                "parent_document_id": rag._artifacts.chunks_by_id[chunk_id][
                    "parent_document_id"
                ],
            }
            for chunk_id in case["candidate_chunk_ids"]
        ]
        expanded_ids = expand_evidence_candidate_chunk_ids(
            question,
            selected,
            chunks_by_parent=chunks_by_parent,
        )
        requirement_queries = kiwi_independent_requirement_queries(question)

        has_introducer_candidate = False
        for candidate_index, chunk_id in enumerate(expanded_ids, 1):
            chunk = rag._artifacts.chunks_by_id[chunk_id]
            document = rag._artifacts.documents_by_id[
                str(chunk["parent_document_id"])
            ]
            units = new_chunk_atomic_units(
                candidate_index=candidate_index,
                chunk_id=chunk_id,
                chunk=chunk,
                document=document,
                temporal=rag.temporal_by_document.get(
                    str(chunk["parent_document_id"]), {}
                ),
            )
            if any(
                _INTRODUCER_MARKER in str(unit.get("context_text") or "")
                for unit in units
            ):
                has_introducer_candidate = True
                break

        if has_introducer_candidate:
            product_evidence_pack._chunk_atomic_units = _legacy_chunk_atomic_units
            try:
                pre_pack = build_atomic_reranked_product_evidence_pack(
                    expanded_ids,
                    question=question,
                    requirement_queries=requirement_queries or None,
                    chunks_by_id=rag._artifacts.chunks_by_id,
                    documents_by_id=rag._artifacts.documents_by_id,
                    temporal_by_document=rag.temporal_by_document,
                    score_pairs=cached_score_pairs,
                    max_units=DEFAULT_EVIDENCE_UNITS,
                    prefilter_per_query=32,
                    reserve_per_query=(
                        3 if len(requirement_queries) > 1 else 1
                    ),
                )
            finally:
                product_evidence_pack._chunk_atomic_units = new_chunk_atomic_units
            post_pack = build_atomic_reranked_product_evidence_pack(
                expanded_ids,
                question=question,
                requirement_queries=requirement_queries or None,
                chunks_by_id=rag._artifacts.chunks_by_id,
                documents_by_id=rag._artifacts.documents_by_id,
                temporal_by_document=rag.temporal_by_document,
                score_pairs=cached_score_pairs,
                max_units=DEFAULT_EVIDENCE_UNITS,
                prefilter_per_query=32,
                reserve_per_query=(3 if len(requirement_queries) > 1 else 1),
            )
        else:
            pre_pack = []
            post_pack = []

        pre_coordinates = [_coordinate(unit) for unit in pre_pack]
        post_coordinates = [_coordinate(unit) for unit in post_pack]
        pack_set_changed = set(pre_coordinates) != set(post_coordinates)
        pack_order_changed = (
            not pack_set_changed and pre_coordinates != post_coordinates
        )
        pre_contexts = {
            _coordinate(unit): str(unit.get("context_text") or "")
            for unit in pre_pack
        }
        changed_context_units = [
            {
                "coordinate": _coordinate(unit),
                "before": pre_contexts[_coordinate(unit)],
                "after": str(unit.get("context_text") or ""),
                "text": unit.get("text") or "",
            }
            for unit in post_pack
            if _coordinate(unit) in pre_contexts
            and pre_contexts[_coordinate(unit)]
            != str(unit.get("context_text") or "")
        ]
        coordinate_mismatches = []
        for unit in post_pack:
            chunk = rag._artifacts.chunks_by_id[str(unit["chunk_id"])]
            source_text = str(chunk.get("display_text") or "")
            if source_text[
                int(unit["start_char"]) : int(unit["end_char"])
            ] != str(unit.get("text") or ""):
                coordinate_mismatches.append(_coordinate(unit))

        record_count = len(case["source_records"])
        context_changed_records += bool(changed_context_units) * record_count
        pack_set_changed_records += pack_set_changed * record_count
        pack_order_changed_records += pack_order_changed * record_count
        coordinate_mismatch_records += bool(coordinate_mismatches) * record_count
        rows.append(
            {
                "type": "case",
                "case_key": index,
                "question": question,
                "candidate_chunk_ids": case["candidate_chunk_ids"],
                "expanded_candidate_chunk_ids": expanded_ids,
                "source_records": case["source_records"],
                "has_introducer_candidate": has_introducer_candidate,
                "context_changed": bool(changed_context_units),
                "changed_context_units": changed_context_units,
                "pack_set_changed": pack_set_changed,
                "pack_order_changed": pack_order_changed,
                "pre_coordinates": pre_coordinates,
                "post_coordinates": post_coordinates,
                "coordinate_mismatches": coordinate_mismatches,
            }
        )
        if index % 10 == 0 or index == len(cases_by_key):
            print(
                json.dumps(
                    {
                        "completed": index,
                        "total": len(cases_by_key),
                        "pack_set_changed": sum(
                            row["pack_set_changed"] for row in rows
                        ),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    chunks_path = Path(rag._artifacts.provenance["chunks_path"])
    if not chunks_path.is_absolute():
        chunks_path = root / chunks_path
    a6 = _a6_comparison(root)
    summary = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "qwen_calls": 0,
        "files_scanned": len(source_paths),
        "saved_record_count": saved_record_count,
        "unique_case_count": len(cases_by_key),
        "table_citation_record_count": table_citation_record_count,
        "introducer_candidate_unique_cases": sum(
            row["has_introducer_candidate"] for row in rows
        ),
        "context_changed_unique_cases": sum(
            row["context_changed"] for row in rows
        ),
        "context_changed_records": context_changed_records,
        "pack_set_changed_unique_cases": sum(
            row["pack_set_changed"] for row in rows
        ),
        "pack_set_changed_records": pack_set_changed_records,
        "pack_order_changed_unique_cases": sum(
            row["pack_order_changed"] for row in rows
        ),
        "pack_order_changed_records": pack_order_changed_records,
        "pack_set_changed_source_records": [
            record
            for row in rows
            if row["pack_set_changed"]
            for record in row["source_records"]
        ],
        "coordinate_mismatch_records": coordinate_mismatch_records,
        "unique_scored_pairs": len(score_cache),
        "scorer_calls": scorer_calls,
        "a6": a6,
        "chunks_path": chunks_path.as_posix(),
        "chunks_sha256": _sha256(chunks_path),
    }
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
