from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable
from src.v3.evaluate_requirement_reranker import requirement_text
from src.v3.evaluate_table_atomic_facts_arm1 import (
    DEFAULT_AS_OF,
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    fuse_rankings,
    is_temporally_eligible,
)


EVALUATOR_VERSION = "table-sidecar-depth-comparison-v3.2"
REPORT_SCHEMA_VERSION = "dnf-table-sidecar-depth-report-v3.2"
MANIFEST_SCHEMA_VERSION = "dnf-table-sidecar-depth-manifest-v3.2"
DEPTHS = (5, 10, 20)

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_RERANKER_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_INDEX_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_index_manifest_"
    "423dfd6ae35bbfa5db1cef0ea1caa61df547ed99c508c998fd134f44f1c4f79d.json"
)
DEFAULT_CONTRACT = Path("docs/v3/table_sidecar_depth_comparison.md")
DEFAULT_OUTPUT_DIR = Path("data/v3/structured")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def coverage_metrics(
    evaluations: list[dict[str, Any]], candidate_ids: dict[str, set[str]]
) -> dict[str, Any]:
    group_hits = 0
    group_total = 0
    question_hits = 0
    question_total = 0
    for evaluation in evaluations:
        groups = evaluation.get("evidence_groups", [])
        if not groups:
            continue
        present = candidate_ids.get(evaluation["dev_id"], set())
        hits = []
        for group in groups:
            hit = bool(present & set(group.get("acceptable_chunk_ids", [])))
            group_hits += hit
            group_total += 1
            hits.append(hit)
        question_hits += all(hits)
        question_total += 1
    return {
        "evidence_groups_hit": group_hits,
        "evidence_group_total": group_total,
        "all_groups_questions": question_hits,
        "question_total": question_total,
    }


def _sidecar_rankings(
    *,
    query: str,
    source_ids: tuple[str, ...],
    bm25: dict[str, Any],
    facts: list[dict[str, Any]],
    embeddings: np.ndarray,
    query_embedding: np.ndarray,
) -> dict[int, list[str]]:
    maximum = max(DEPTHS)
    lexical = search_bm25(
        bm25,
        query,
        top_k=maximum,
        policy=SearchPolicy(
            allowed_statuses=("current", "active", "upcoming"),
            as_of=DEFAULT_AS_OF,
            source_ids=source_ids,
        ),
    )
    lexical_ids = [row["chunk_id"] for row in lexical]
    allowed = [
        index
        for index, fact in enumerate(facts)
        if fact["source_id"] in source_ids
        and is_temporally_eligible(fact, as_of=DEFAULT_AS_OF)
    ]
    if allowed:
        dense_scores = embeddings[allowed] @ query_embedding
        dense_order = sorted(
            zip(allowed, dense_scores.tolist(), strict=True),
            key=lambda item: (-float(item[1]), facts[item[0]]["fact_id"]),
        )[:maximum]
        dense_ids = [facts[index]["fact_id"] for index, _ in dense_order]
    else:
        dense_ids = []
    return {
        depth: fuse_rankings(lexical_ids[:depth], dense_ids[:depth])[:depth]
        for depth in DEPTHS
    }


def _markdown(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    lines = [
        "# v3.2 table sidecar top-5/10/20 A/B",
        "",
        f"Decision: **{report['decision']}**. Runtime/canonical was not promoted.",
        "",
        "| Sidecar fused depth | Evidence groups hit | All-groups questions | Incremental groups | Regressions |",
        "|---:|---:|---:|---:|---:|",
        f"| OFF | {baseline['evidence_groups_hit']}/{baseline['evidence_group_total']} | {baseline['all_groups_questions']}/{baseline['question_total']} | 0 | 0 |",
    ]
    for depth in DEPTHS:
        metrics = report["depths"][str(depth)]
        lines.append(
            f"| {depth} | {metrics['evidence_groups_hit']}/{metrics['evidence_group_total']} | {metrics['all_groups_questions']}/{metrics['question_total']} | {metrics['incremental_evidence_groups']} | {metrics['regression_count']} |"
        )
    lines.extend(
        [
            "",
            "Parent candidates are frozen and unioned at every depth. These numbers measure candidate recall only; answer-level false-full risk is not promoted away by this diagnostic.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    root = Path(__file__).resolve().parents[2]
    chunks = read_jsonl(root / DEFAULT_CHUNKS)
    evaluations = read_jsonl(root / DEFAULT_CANARY) + read_jsonl(root / DEFAULT_DEV)
    enumerations = {row["case_id"]: row for row in read_jsonl(root / DEFAULT_ENUMERATION)}
    scores = {row["case_id"]: row for row in read_jsonl(root / DEFAULT_RERANKER_SCORES)}
    index_manifest = json.loads((root / DEFAULT_INDEX_MANIFEST).read_text(encoding="utf-8"))
    bm25_path = root / index_manifest["bm25"]["path"]
    metadata_path = root / index_manifest["dense"]["metadata_path"]
    embeddings_path = root / index_manifest["dense"]["path"]
    for path, expected in (
        (bm25_path, index_manifest["bm25"]["sha256"]),
        (metadata_path, index_manifest["dense"]["metadata_sha256"]),
        (embeddings_path, index_manifest["dense"]["sha256"]),
    ):
        if file_sha256(path) != expected:
            raise RuntimeError(f"Frozen sidecar hash mismatch: {path}")
    bm25 = json.loads(bm25_path.read_text(encoding="utf-8"))
    facts = read_jsonl(metadata_path)
    embeddings = np.fromfile(embeddings_path, dtype="<f4").reshape(
        len(facts), index_manifest["dense"]["dimension"]
    )
    chunks_by_id = {row["chunk_id"]: row for row in chunks}

    baseline_by_case: dict[str, set[str]] = {}
    queries = []
    request_rows = []
    for evaluation in evaluations:
        case_id = evaluation["dev_id"]
        baseline = {
            candidate["chunk_id"]
            for requirement in scores[case_id]["requirements"]
            for candidate in requirement["candidates"]
        }
        baseline_by_case[case_id] = baseline
        source_ids = tuple(
            sorted({chunks_by_id[chunk_id]["source_id"] for chunk_id in baseline})
        )
        for requirement in enumerations[case_id]["requirements"]:
            query = requirement_text(requirement)
            queries.append(query)
            request_rows.append(
                {"case_id": case_id, "query": query, "source_ids": source_ids}
            )

    model = SentenceTransformer(
        EMBEDDING_MODEL,
        revision=EMBEDDING_REVISION,
        device=device,
        local_files_only=True,
    )
    model.max_seq_length = 512
    unique_queries = sorted(set(queries))
    vectors = model.encode(
        unique_queries,
        batch_size=16,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    vector_by_query = {
        query: np.asarray(vector, dtype=np.float32)
        for query, vector in zip(unique_queries, vectors, strict=True)
    }

    sidecar_chunks_by_depth = {
        depth: {evaluation["dev_id"]: set() for evaluation in evaluations}
        for depth in DEPTHS
    }
    fact_by_id = {row["fact_id"]: row for row in facts}
    for request in request_rows:
        rankings = _sidecar_rankings(
            query=request["query"],
            source_ids=request["source_ids"],
            bm25=bm25,
            facts=facts,
            embeddings=embeddings,
            query_embedding=vector_by_query[request["query"]],
        )
        for depth, fact_ids in rankings.items():
            sidecar_chunks_by_depth[depth][request["case_id"]].update(
                fact_by_id[fact_id]["source_chunk_id"] for fact_id in fact_ids
            )

    baseline = coverage_metrics(evaluations, baseline_by_case)
    depths = {}
    for depth in DEPTHS:
        arm_candidates = {
            case_id: baseline_by_case[case_id] | sidecar_chunks_by_depth[depth][case_id]
            for case_id in baseline_by_case
        }
        metrics = coverage_metrics(evaluations, arm_candidates)
        regressions = []
        for evaluation in evaluations:
            case_id = evaluation["dev_id"]
            for group in evaluation.get("evidence_groups", []):
                acceptable = set(group.get("acceptable_chunk_ids", []))
                if baseline_by_case[case_id] & acceptable and not arm_candidates[case_id] & acceptable:
                    regressions.append({"case_id": case_id, "group_id": group["group_id"]})
        metrics["incremental_evidence_groups"] = metrics["evidence_groups_hit"] - baseline["evidence_groups_hit"]
        metrics["regression_count"] = len(regressions)
        metrics["average_sidecar_source_chunks_per_question"] = round(
            sum(len(values) for values in sidecar_chunks_by_depth[depth].values())
            / len(evaluations),
            4,
        )
        depths[str(depth)] = metrics
    best_depth = min(
        DEPTHS,
        key=lambda depth: (
            -depths[str(depth)]["evidence_groups_hit"],
            depths[str(depth)]["average_sidecar_source_chunks_per_question"],
            depth,
        ),
    )
    any_improvement = depths[str(best_depth)]["evidence_groups_hit"] > baseline["evidence_groups_hit"]
    decision = (
        f"GO_DEPTH_{best_depth}_CANDIDATE_RECALL_ONLY_NOT_PROMOTED"
        if any_improvement
        else "NO_ADDITIONAL_RECALL_COMPARISON_COMPLETE"
    )
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "status": "development_only_not_promoted",
        "model": {"name": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION, "device": device},
        "baseline": baseline,
        "depths": depths,
        "best_depth_by_recall_then_cost": best_depth,
        "decision": decision,
        "scope": {"training": False, "reindexing": False, "gold_used_for_search": False, "runtime_changed": False, "promoted": False},
    }
    report_dir = root / DEFAULT_REPORT_DIR
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = report_dir / f"table_sidecar_depth_comparison_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"table_sidecar_depth_comparison_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    inputs = {"chunks": DEFAULT_CHUNKS, "adaptive_dev": DEFAULT_DEV, "downgraded_canary": DEFAULT_CANARY, "enumeration": DEFAULT_ENUMERATION, "reranker_scores": DEFAULT_RERANKER_SCORES, "sidecar_index_manifest": DEFAULT_INDEX_MANIFEST, "contract": DEFAULT_CONTRACT, "evaluator_source": Path(__file__).resolve().relative_to(root)}
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {name: {"path": path.as_posix(), "sha256": file_sha256(root / path)} for name, path in inputs.items()},
        "artifacts": {"report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha}, "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha}},
        "decision": decision,
        "promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / DEFAULT_OUTPUT_DIR / f"table_sidecar_depth_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"manifest": manifest_path.relative_to(root).as_posix(), "report": report_path.relative_to(root).as_posix(), "report_markdown": markdown_path.relative_to(root).as_posix(), **report}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
