from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.product_evidence_pack import (
    build_atomic_reranked_product_evidence_pack,
    kiwi_independent_requirement_queries,
)
from src.v3.product_free_rag import (
    DEFAULT_EVIDENCE_UNITS,
    ProductFreeRAG,
    expand_evidence_candidate_chunk_ids,
)


A6_INPUT = Path(
    "data/v3/evaluation/product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc"
    "689b65dc.jsonl"
)
A6_SAVED = Path(
    "reports/v3/product_free_rag_a6_one_shot_"
    "4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c"
    "78499.jsonl"
)
PRE_OUTPUT = Path(
    "reports/v3/product_header_metadata_pack_pre_20260805.jsonl"
)
POST_OUTPUT = Path(
    "reports/v3/product_header_metadata_pack_post_20260805.jsonl"
)
RUNNER_VERSION = "product-header-metadata-pack-diagnostic-v1"

_HEADER_TIMESTAMP = re.compile(
    r"20\d{2}[.-]\d{2}[.-]\d{2}\s+\d{1,2}:\d{2}"
)
_HEADER_VIEW_COUNT = re.compile(r"\d{1,3}(?:,\d{3})+")


def diagnostic_header_metadata_spans(
    text: str,
) -> list[tuple[int, int, str]]:
    lines = []
    for match in re.finditer(r"[^\r\n]+", text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        lines.append(
            (
                match.start() + left,
                match.start() + right,
                text[match.start() + left : match.start() + right],
            )
        )
        if len(lines) >= 6:
            break
    if len(lines) < 3 or not lines[0][2].startswith("#"):
        return []
    timestamp_indexes = [
        index
        for index, (_, _, line) in enumerate(lines)
        if 2 <= index <= 4 and _HEADER_TIMESTAMP.fullmatch(line)
    ]
    if len(timestamp_indexes) != 1:
        return []
    timestamp_index = timestamp_indexes[0]
    start, end, _ = lines[timestamp_index]
    spans = [(start, end, "published_timestamp")]
    view_index = timestamp_index + 1
    if view_index < len(lines):
        view_start, view_end, view_line = lines[view_index]
        if _HEADER_VIEW_COUNT.fullmatch(view_line):
            spans.append((view_start, view_end, "view_count"))
    return spans


def _overlaps(
    evidence_pack: list[dict[str, Any]],
    gold: dict[str, Any],
) -> bool:
    return any(
        str(unit.get("chunk_id")) == str(gold.get("chunk_id"))
        and int(unit.get("start_char", -1)) < int(gold.get("end_char", -1))
        and int(unit.get("end_char", -1)) > int(gold.get("start_char", -1))
        for unit in evidence_pack
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild saved A6 packs without calling Qwen"
    )
    parser.add_argument("--phase", choices=("pre", "post"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    requested = args.output or (
        PRE_OUTPUT if args.phase == "pre" else POST_OUTPUT
    )
    output = requested if requested.is_absolute() else root / requested
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")

    frozen_by_slot = {
        row["slot_ordinal"]: row for row in read_jsonl(root / A6_INPUT)
    }
    saved_by_slot = {
        row["slot_ordinal"]: row
        for row in read_jsonl(root / A6_SAVED)
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
    chunks_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in rag._artifacts.chunks_by_id.values():
        chunks_by_parent[str(chunk["parent_document_id"])].append(chunk)

    header_chunk_count = 0
    header_kind_counts: Counter[str] = Counter()
    for chunk in rag._artifacts.chunks_by_id.values():
        spans = diagnostic_header_metadata_spans(
            str(chunk.get("display_text") or "")
        )
        if spans:
            header_chunk_count += 1
            header_kind_counts.update(kind for _, _, kind in spans)

    rows = []
    all_visibility: dict[str, bool] = {}
    coordinate_mismatch_case_refs = []
    for slot in range(1, 33):
        frozen = frozen_by_slot[slot]
        saved = saved_by_slot[slot]
        question = frozen["question_text"]
        requirement_queries = kiwi_independent_requirement_queries(question)
        selected = saved["result"].get("candidates") or []
        candidate_ids = expand_evidence_candidate_chunk_ids(
            question,
            selected,
            chunks_by_parent=chunks_by_parent,
        )
        evidence_pack = build_atomic_reranked_product_evidence_pack(
            candidate_ids,
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
        gold_visibility = {}
        for requirement in frozen["requirements"]:
            for index, gold in enumerate(
                requirement.get("acceptable_evidence_units") or [],
                1,
            ):
                key = (
                    f"A6-{slot}:{requirement['requirement_id']}:"
                    f"{index}:{gold['chunk_id']}:{gold['start_char']}:"
                    f"{gold['end_char']}"
                )
                visible = _overlaps(evidence_pack, gold)
                gold_visibility[key] = visible
                all_visibility[key] = visible
        header_units = []
        coordinate_mismatches = []
        for unit in evidence_pack:
            chunk = rag._artifacts.chunks_by_id[str(unit["chunk_id"])]
            source_text = str(chunk.get("display_text") or "")
            start_char = int(unit["start_char"])
            end_char = int(unit["end_char"])
            if source_text[start_char:end_char] != str(unit.get("text") or ""):
                coordinate_mismatches.append(
                    {
                        "evidence_ref": unit["evidence_ref"],
                        "chunk_id": unit["chunk_id"],
                        "start_char": start_char,
                        "end_char": end_char,
                        "text": unit.get("text") or "",
                        "source_slice": source_text[start_char:end_char],
                    }
                )
            for start, end, kind in diagnostic_header_metadata_spans(
                source_text
            ):
                if (
                    int(unit["start_char"]) >= start
                    and int(unit["end_char"]) <= end
                ):
                    header_units.append(
                        {
                            "evidence_ref": unit["evidence_ref"],
                            "chunk_id": unit["chunk_id"],
                            "start_char": unit["start_char"],
                            "end_char": unit["end_char"],
                            "text": unit["text"],
                            "header_kind": kind,
                        }
                    )
        if coordinate_mismatches:
            coordinate_mismatch_case_refs.append(f"A6-{slot}")
        rows.append(
            {
                "type": "case",
                "phase": args.phase,
                "case_ref": f"A6-{slot}",
                "question": question,
                "candidate_chunk_ids": candidate_ids,
                "evidence_pack": evidence_pack,
                "gold_visibility": gold_visibility,
                "header_units": header_units,
                "coordinate_mismatches": coordinate_mismatches,
            }
        )
        print(
            json.dumps(
                {
                    "case_ref": f"A6-{slot}",
                    "gold_visible": sum(gold_visibility.values()),
                    "gold_total": len(gold_visibility),
                    "header_units": len(header_units),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    chunks_path = Path(rag._artifacts.provenance["chunks_path"])
    if not chunks_path.is_absolute():
        chunks_path = root / chunks_path
    summary: dict[str, Any] = {
        "type": "summary",
        "runner_version": RUNNER_VERSION,
        "phase": args.phase,
        "qwen_calls": 0,
        "case_count": len(rows),
        "gold_coordinate_count": len(all_visibility),
        "gold_visible_count": sum(all_visibility.values()),
        "gold_visibility": all_visibility,
        "header_chunk_count": header_chunk_count,
        "header_kind_counts": dict(header_kind_counts),
        "pack_header_unit_case_refs": [
            row["case_ref"] for row in rows if row["header_units"]
        ],
        "coordinate_restoration_exact_cases": (
            len(rows) - len(coordinate_mismatch_case_refs)
        ),
        "coordinate_mismatch_case_refs": coordinate_mismatch_case_refs,
        "chunks_path": chunks_path.as_posix(),
        "chunks_sha256": _sha256(chunks_path),
    }
    if args.phase == "post":
        pre_rows = read_jsonl(root / PRE_OUTPUT)
        pre_summary = next(
            row for row in pre_rows if row.get("type") == "summary"
        )
        changed_visibility = [
            key
            for key, visible in all_visibility.items()
            if pre_summary["gold_visibility"].get(key) != visible
        ]
        summary["pre_comparison"] = {
            "gold_visibility_changed": changed_visibility,
            "gold_visibility_unchanged": not changed_visibility,
            "chunk_sha_changed": (
                pre_summary["chunks_sha256"] != summary["chunks_sha256"]
            ),
        }
    write_jsonl(output, [*rows, summary])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
