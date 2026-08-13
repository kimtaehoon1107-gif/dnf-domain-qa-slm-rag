from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from itertools import permutations
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.question_router import (
    DEFAULT_AS_OF,
    build_source_entity_index,
    route_question,
    search_policy_from_route,
)
from src.v3.temporal_policy import (
    restrict_bm25_index,
    resolve_policy_revisions,
    search_policy_for_resolution,
)


DECOMPOSITION_SCHEMA_VERSION = "dnf_question_decomposition_v3.1"
MANIFEST_SCHEMA_VERSION = "dnf_question_decomposition_manifest_v3.1"
REPORT_SCHEMA_VERSION = "dnf_question_decomposition_report_v3.1"
DECOMPOSER_VERSION = "dnf-question-decomposer-v3.1.0"
BUILT_AT = "2026-07-19T08:30:00+09:00"

DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_BM25_INDEX = Path(
    "data/v3/indexes/"
    "bm25_index_af7de9bbf691aabaee464a2fe02facdf1f4b11de70d029967508357cab4948a2.json"
)
DEFAULT_OVERLAY = Path(
    "data/v3/temporal/"
    "account_policy_revisions_"
    "8320c9003c94225bd39a90d69bed432d84bd3bd5a64b38a68debdd86f7cb247c.jsonl"
)
DEFAULT_DEV_SET = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_ROUTER_CASES = Path(
    "data/v3/router/"
    "question_router_cases_"
    "caa3ff01684fbee3937ef4115c283398c3d4983fd1187680ff561a5438f894c9.jsonl"
)
DEFAULT_ROUTER_MANIFEST = Path(
    "data/v3/router/"
    "question_router_manifest_"
    "05db67ce7dea7779b40b679b861f082643644e11c2ec20c2de972d8b817d464a.json"
)
DEFAULT_BUILDER_SOURCE = Path("src/v3/question_decomposer.py")
DEFAULT_ROUTER_SOURCE = Path("src/v3/question_router.py")
DEFAULT_SCHEMA_SOURCE = Path("src/v3/schemas.py")
DEFAULT_CONTRACT = Path("docs/v3/question_decomposition.md")

MONTH_PAIR_PATTERN = re.compile(
    r"^(?P<first>\d{1,2})월과\s+(?P<second>\d{1,2})월\s+"
    r"(?P<subject>.+?)은\s+각각\s+(?P<predicate>.+?)[?.]?$"
)
SHARED_ATTRIBUTE_PATTERN = re.compile(
    r"^(?P<left>.+?)와\s+(?P<right>.+?)의\s+"
    r"(?P<attribute>.+?)(?:을|를)\s+비교해줘[?.]?$"
)
PAIRED_CLAUSE_PATTERN = re.compile(
    r"^(?P<left>.+?)(?:과|와)\s+(?P<right>.+?)(?:을|를)\s+"
    r"(?P<instruction>각각\s+알려줘|함께\s+정리해줘)[?.]?$"
)
SOURCE_LABELS = {
    "dnf_account_policy": "운영정책",
    "dnf_event": "이벤트",
    "dnf_faq": "FAQ",
    "dnf_game_guide": "게임가이드",
    "dnf_monthly_item": "이달의 아이템",
    "dnf_notice": "공식 공지",
    "dnf_seria_shop": "세리아 상점",
    "dnf_update": "업데이트",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _question(text: str) -> str:
    normalized = " ".join(text.strip().rstrip(".?").split())
    return f"{normalized}?"


def _subquestion_id(parent_id: str, ordinal: int, question: str) -> str:
    payload = f"{parent_id}\n{ordinal}\n{question}".encode("utf-8")
    return f"subquestion_sha256_{hashlib.sha256(payload).hexdigest()}"


def _build_subquestions(
    parent_id: str,
    values: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "subquestion_id": _subquestion_id(parent_id, ordinal, question),
            "ordinal": ordinal,
            "question": question,
            "relationship": relationship,
            "time_hint": time_hint,
            "source_hint": None,
        }
        for ordinal, (question, relationship, time_hint) in enumerate(values, start=1)
    ]


def decompose_question(
    parent_id: str,
    question: str,
    *,
    as_of: str = DEFAULT_AS_OF,
) -> dict[str, Any]:
    normalized = " ".join(question.strip().split())
    if not normalized:
        raise RuntimeError("question must not be empty")
    current = date.fromisoformat(as_of)

    month_match = MONTH_PAIR_PATTERN.match(normalized)
    if month_match:
        subject = month_match.group("subject")
        predicate = month_match.group("predicate")
        values = []
        for relationship, month_text in (
            ("first_period", month_match.group("first")),
            ("second_period", month_match.group("second")),
        ):
            month = int(month_text)
            if not 1 <= month <= 12:
                raise RuntimeError(f"Invalid month in decomposition: {month}")
            if month == current.month:
                child = _question(f"{month}월 {subject}은 {predicate}")
                time_hint = "current"
            else:
                year = current.year if month < current.month else current.year - 1
                child = _question(
                    f"{year}년 {month}월 당시 {subject}은 {predicate}"
                )
                time_hint = "historical"
            values.append((child, relationship, time_hint))
        strategy = "month_pair"
    else:
        shared_match = SHARED_ATTRIBUTE_PATTERN.match(normalized)
        if shared_match:
            attribute = shared_match.group("attribute")
            split_attribute = re.match(
                r"^(?P<left>[^·]+)·(?P<right>\S+)\s+(?P<common>.+)$",
                attribute,
            )
            if split_attribute:
                left_attribute = (
                    f"{split_attribute.group('left')} {split_attribute.group('common')}"
                )
                right_attribute = (
                    f"{split_attribute.group('right')} {split_attribute.group('common')}"
                )
            else:
                left_attribute = attribute
                right_attribute = attribute
            values = [
                (
                    _question(
                        f"{shared_match.group('left')}의 {left_attribute}은"
                    ),
                    "left_comparison_item",
                    "inherit_parent",
                ),
                (
                    _question(
                        f"{shared_match.group('right')}의 {right_attribute}은"
                    ),
                    "right_comparison_item",
                    "inherit_parent",
                ),
            ]
            strategy = "shared_attribute_comparison"
        else:
            clause_match = PAIRED_CLAUSE_PATTERN.match(normalized)
            if not clause_match:
                raise RuntimeError("Unsupported decomposition pattern")
            values = [
                (
                    _question(f"{clause_match.group('left')}은"),
                    "first_clause",
                    "inherit_parent",
                ),
                (
                    _question(f"{clause_match.group('right')}은"),
                    "second_clause",
                    "inherit_parent",
                ),
            ]
            strategy = "paired_clauses"
    return {
        "decomposition_schema_version": DECOMPOSITION_SCHEMA_VERSION,
        "parent_id": parent_id,
        "parent_question": normalized,
        "strategy": strategy,
        "subquestions": _build_subquestions(parent_id, values),
    }


def apply_parent_source_hints(
    decomposition: dict[str, Any],
    parent_route: dict[str, Any],
    bm25_index: dict[str, Any],
    *,
    as_of: str = DEFAULT_AS_OF,
) -> dict[str, Any]:
    children = decomposition["subquestions"]
    sources = parent_route["source_ids"]
    if not sources:
        raise RuntimeError("Decomposition parent has no source route")
    if len(sources) == 1:
        assignments = [sources[0]] * len(children)
    elif len(sources) == len(children) == 2:
        scores = {}
        for child_index, child in enumerate(children):
            for source_id in sources:
                hits = search_bm25(
                    bm25_index,
                    child["question"],
                    top_k=1,
                    policy=SearchPolicy(
                        default_exposure_only=True,
                        allowed_statuses=("current", "upcoming"),
                        include_review_required=False,
                        as_of=as_of,
                        source_ids=(source_id,),
                    ),
                )
                scores[(child_index, source_id)] = hits[0]["score"] if hits else 0.0
        assignment_options = list(permutations(sorted(sources)))
        assignments = list(
            sorted(
                assignment_options,
                key=lambda option: (
                    -sum(
                        scores[(child_index, source_id)]
                        for child_index, source_id in enumerate(option)
                    ),
                    option,
                ),
            )[0]
        )
    else:
        raise RuntimeError("Unsupported child/source cardinality")

    output = []
    for child, source_id in zip(children, assignments):
        label = SOURCE_LABELS[source_id]
        question = _question(f"{label} 기준으로 {child['question']}")
        output.append(
            {
                **child,
                "subquestion_id": _subquestion_id(
                    decomposition["parent_id"], child["ordinal"], question
                ),
                "question": question,
                "source_hint": source_id,
            }
        )
    return {**decomposition, "subquestions": output}


def _allowed_document_ids(
    route: dict[str, Any], documents: list[dict[str, Any]]
) -> list[str]:
    allowed_sources = set(route["source_ids"])
    allowed_kinds = set(route["source_kinds"])
    return sorted(
        row["document_id"]
        for row in documents
        if row["source_id"] in allowed_sources
        and (not allowed_kinds or row["source_kind"] in allowed_kinds)
    )


def route_and_search_subquestion(
    subquestion: dict[str, Any],
    *,
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    bm25_index: dict[str, Any],
    overlay_rows: list[dict[str, Any]],
    source_entity_index: dict[str, list[frozenset[str]]],
    top_k: int = 10,
    as_of: str = DEFAULT_AS_OF,
) -> dict[str, Any]:
    question = subquestion["question"]
    global_hits = search_bm25(
        bm25_index,
        question,
        top_k=20,
        policy=SearchPolicy(as_of=as_of),
    )
    route = route_question(
        question,
        candidate_hits=global_hits,
        documents=documents,
        source_entity_index=source_entity_index,
        overlay_rows=overlay_rows,
    )
    if route["route_action"] != "retrieve":
        return {"subquestion": subquestion, "route": route, "hits": []}
    if route["source_ids"] == ["dnf_account_policy"]:
        resolution = resolve_policy_revisions(
            overlay_rows,
            mode=route["time_scope"],
            as_of=route["temporal_as_of"],
        )
        restricted = restrict_bm25_index(
            bm25_index, resolution["allowed_document_ids"]
        )
        hits = search_bm25(
            restricted,
            question,
            top_k=top_k,
            policy=search_policy_for_resolution(resolution),
        )
    else:
        restricted = restrict_bm25_index(
            bm25_index, _allowed_document_ids(route, documents)
        )
        hits = search_bm25(
            restricted,
            question,
            top_k=top_k,
            policy=search_policy_from_route(route, current_as_of=as_of),
        )
    return {"subquestion": subquestion, "route": route, "hits": hits}


def freeze_question_decomposition(
    *,
    root: Path,
    artifact_root: Path | None = None,
    documents_path: Path,
    chunks_path: Path,
    bm25_index_path: Path,
    overlay_path: Path,
    dev_set_path: Path,
    router_cases_path: Path,
    router_manifest_path: Path,
    builder_source_path: Path,
    router_source_path: Path,
    schema_source_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    artifact_root = root if artifact_root is None else artifact_root.resolve()
    documents = read_jsonl(documents_path)
    chunks = read_jsonl(chunks_path)
    overlay_rows = read_jsonl(overlay_path)
    dev_rows = read_jsonl(dev_set_path)
    router_cases = read_jsonl(router_cases_path)
    bm25_index = json.loads(bm25_index_path.read_text(encoding="utf-8"))
    source_entity_index = build_source_entity_index(documents, chunks)
    router_by_id = {row["case_id"]: row for row in router_cases}

    input_paths = {
        "documents": documents_path,
        "chunks": chunks_path,
        "bm25_index": bm25_index_path,
        "temporal_overlay": overlay_path,
        "adaptive_retrieval_dev": dev_set_path,
        "question_router_cases": router_cases_path,
        "question_router_manifest": router_manifest_path,
        "builder_source": builder_source_path,
        "router_source": router_source_path,
        "schema_source": schema_source_path,
        "contract": contract_path,
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}

    multi_rows = [row for row in dev_rows if row["query_kind"] == "multi_evidence"]
    cases = []
    parse_errors = 0
    child_count = 0
    recursive_routes = 0
    clarification_routes = 0
    empty_child_results = 0
    parent_source_coverage_errors = 0
    parent_time_coverage_errors = 0
    evidence_group_count = 0
    evidence_group_hits = 0
    child_group_specificity_errors = 0
    for dev in multi_rows:
        parent_router_case = router_by_id.get(dev["dev_id"])
        if parent_router_case is None:
            raise RuntimeError(f"Missing parent Router case: {dev['dev_id']}")
        parent_route = parent_router_case["route"]
        if not parent_route["needs_decomposition"]:
            raise RuntimeError(f"Parent was not routed to decomposition: {dev['dev_id']}")
        try:
            decomposition = decompose_question(dev["dev_id"], dev["question"])
            decomposition = apply_parent_source_hints(
                decomposition, parent_route, bm25_index
            )
        except RuntimeError:
            parse_errors += 1
            raise
        children = [
            route_and_search_subquestion(
                subquestion,
                documents=documents,
                chunks=chunks,
                bm25_index=bm25_index,
                overlay_rows=overlay_rows,
                source_entity_index=source_entity_index,
            )
            for subquestion in decomposition["subquestions"]
        ]
        child_count += len(children)
        recursive_routes += sum(
            child["route"]["needs_decomposition"] for child in children
        )
        clarification_routes += sum(
            child["route"]["needs_clarification"] for child in children
        )
        empty_child_results += sum(not child["hits"] for child in children)
        child_source_union = sorted(
            {
                source_id
                for child in children
                for source_id in child["route"]["source_ids"]
            }
        )
        parent_source_coverage_errors += child_source_union != sorted(dev["source_ids"])
        child_time_scopes = {child["route"]["time_scope"] for child in children}
        expected_time_scopes = (
            {"current", "historical"}
            if dev["time_scope"] == "mixed"
            else {dev["time_scope"]}
        )
        parent_time_coverage_errors += child_time_scopes != expected_time_scopes

        group_hits_by_child = []
        covered_groups = set()
        for child in children:
            hit_ids = {row["chunk_id"] for row in child["hits"]}
            child_groups = sorted(
                group["group_id"]
                for group in dev["evidence_groups"]
                if hit_ids.intersection(group["acceptable_chunk_ids"])
            )
            group_hits_by_child.append(child_groups)
            covered_groups.update(child_groups)
            child_group_specificity_errors += len(child_groups) != 1
        expected_groups = {group["group_id"] for group in dev["evidence_groups"]}
        evidence_group_count += len(expected_groups)
        evidence_group_hits += len(covered_groups & expected_groups)
        child_rows = []
        for child, child_groups in zip(children, group_hits_by_child):
            child_rows.append(
                {
                    "subquestion": child["subquestion"],
                    "route": child["route"],
                    "bm25_hit_chunk_ids": [row["chunk_id"] for row in child["hits"]],
                    "bm25_hit_parent_document_ids": sorted(
                        {row["parent_document_id"] for row in child["hits"]}
                    ),
                    "matched_evidence_group_ids": child_groups,
                }
            )
        cases.append(
            {
                "case_id": dev["dev_id"],
                "evaluation_role": "adaptive_dev_not_final_benchmark",
                "parent_question": dev["question"],
                "parent_route": parent_route,
                "decomposition": decomposition,
                "children": child_rows,
                "expected_parent_source_ids": sorted(dev["source_ids"]),
                "child_source_union": child_source_union,
                "expected_parent_time_scope": dev["time_scope"],
                "child_time_scopes": sorted(child_time_scopes),
                "expected_evidence_group_ids": sorted(expected_groups),
                "covered_evidence_group_ids": sorted(covered_groups),
            }
        )

    gates = {
        "adaptive_multi_parent_count_4": len(multi_rows) == 4,
        "parse_errors_0": parse_errors == 0,
        "child_count_8": child_count == 8,
        "recursive_child_routes_0": recursive_routes == 0,
        "child_clarification_routes_0": clarification_routes == 0,
        "empty_child_bm25_results_0": empty_child_results == 0,
        "parent_source_coverage_errors_0": parent_source_coverage_errors == 0,
        "parent_time_coverage_errors_0": parent_time_coverage_errors == 0,
        "evidence_group_hit_at_10_all": evidence_group_hits == evidence_group_count,
        "each_child_matches_one_evidence_group": child_group_specificity_errors == 0,
    }
    go = all(gates.values())
    decisions = {
        "deterministic_question_decomposition": "GO" if go else "NO-GO",
        "child_source_time_rerouting": "GO" if go else "NO-GO",
        "child_bm25_evidence_pilot": "GO" if go else "NO-GO",
        "child_hybrid_retrieval": "NO-GO",
        "result_merge_and_conflict_resolution": "NO-GO",
        "free_form_generator_generation": "NO-GO",
        "final_benchmark": "NO-GO",
    }
    metrics = {
        "adaptive_multi_parents": len(multi_rows),
        "children": child_count,
        "parse_errors": parse_errors,
        "recursive_child_routes": recursive_routes,
        "child_clarification_routes": clarification_routes,
        "empty_child_bm25_results": empty_child_results,
        "parent_source_coverage_errors": parent_source_coverage_errors,
        "parent_time_coverage_errors": parent_time_coverage_errors,
        "evidence_group_hits_at_10": evidence_group_hits,
        "evidence_group_count": evidence_group_count,
        "child_group_specificity_errors": child_group_specificity_errors,
    }

    cases = sorted(cases, key=lambda row: row["case_id"])
    cases_bytes = _serialize_jsonl(cases, lambda row: row["case_id"])
    cases_sha = _sha256_bytes(cases_bytes)
    output_dir = artifact_root / "data/v3/decomposition"
    report_dir = artifact_root / "reports/v3"
    cases_path = output_dir / f"question_decomposition_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "decomposer_version": DECOMPOSER_VERSION,
        "built_at": BUILT_AT,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "cases": {
            "path": _relative(artifact_root, cases_path),
            "sha256": cases_sha,
            "row_count": len(cases),
            "child_count": child_count,
        },
        "metrics": metrics,
        "gates": gates,
        "decisions": decisions,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = output_dir / f"question_decomposition_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "decomposer_version": DECOMPOSER_VERSION,
        "built_at": BUILT_AT,
        "evaluation_role": "adaptive_dev_not_final_benchmark",
        "cases_sha256": cases_sha,
        "manifest_sha256": manifest_sha,
        "metrics": metrics,
        "gates": gates,
        "decisions": decisions,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"question_decomposition_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown = f"""# DNF RAG v3 Question Decomposition pilot

## Decision

- deterministic decomposition: **{decisions['deterministic_question_decomposition']}**
- child source/time rerouting: **{decisions['child_source_time_rerouting']}**
- child BM25 evidence pilot: **{decisions['child_bm25_evidence_pilot']}**
- child hybrid retrieval / merge / Generator / final benchmark: **NO-GO**

## Adaptive dev pilot

- multi-document parents: {len(multi_rows)}
- generated children: {child_count}
- parse errors: {parse_errors}
- recursive child routes: {recursive_routes}
- child clarification routes: {clarification_routes}
- empty child BM25 results: {empty_child_results}
- parent source coverage errors: {parent_source_coverage_errors}
- parent time coverage errors: {parent_time_coverage_errors}
- evidence-group hit@10: {evidence_group_hits}/{evidence_group_count}
- child evidence-group specificity errors: {child_group_specificity_errors}

This pilot uses only the four adaptive multi-evidence development questions. Gold
evidence IDs are used after decomposition and routing solely to audit hit coverage;
they are not inputs to the decomposition rules or child Router. Unsupported sentence
patterns fail closed instead of being split heuristically.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"question_decomposition_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed while freezing decomposition: {name}")
    return {
        "cases_path": str(cases_path),
        "cases_sha256": cases_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "metrics": metrics,
        "gates": gates,
        "decisions": decisions,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build and audit the v3 Question Decomposition pilot"
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--documents", type=Path, default=root / DEFAULT_DOCUMENTS)
    parser.add_argument("--chunks", type=Path, default=root / DEFAULT_CHUNKS)
    parser.add_argument("--bm25-index", type=Path, default=root / DEFAULT_BM25_INDEX)
    parser.add_argument("--overlay", type=Path, default=root / DEFAULT_OVERLAY)
    parser.add_argument("--dev-set", type=Path, default=root / DEFAULT_DEV_SET)
    parser.add_argument(
        "--router-cases", type=Path, default=root / DEFAULT_ROUTER_CASES
    )
    parser.add_argument(
        "--router-manifest", type=Path, default=root / DEFAULT_ROUTER_MANIFEST
    )
    parser.add_argument(
        "--builder-source", type=Path, default=root / DEFAULT_BUILDER_SOURCE
    )
    parser.add_argument(
        "--router-source", type=Path, default=root / DEFAULT_ROUTER_SOURCE
    )
    parser.add_argument(
        "--schema-source", type=Path, default=root / DEFAULT_SCHEMA_SOURCE
    )
    parser.add_argument("--contract", type=Path, default=root / DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = freeze_question_decomposition(
        root=args.root.resolve(),
        documents_path=args.documents.resolve(),
        chunks_path=args.chunks.resolve(),
        bm25_index_path=args.bm25_index.resolve(),
        overlay_path=args.overlay.resolve(),
        dev_set_path=args.dev_set.resolve(),
        router_cases_path=args.router_cases.resolve(),
        router_manifest_path=args.router_manifest.resolve(),
        builder_source_path=args.builder_source.resolve(),
        router_source_path=args.router_source.resolve(),
        schema_source_path=args.schema_source.resolve(),
        contract_path=args.contract.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
