from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.assemble_table_group_answers import (
    ASSEMBLER_VERSION as TABLE_GROUP_ASSEMBLER_VERSION,
    assemble_table_group_answers,
)
from src.v3.build_bm25 import SearchPolicy, build_bm25_index, search_bm25
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_requirement_reranker import requirement_text
from src.v3.evaluate_router_backbone_ab import _score_arm, simulate_arm


EVALUATOR_VERSION = "table-atomic-facts-arm1-ab-v3.2.2"
CASE_SCHEMA_VERSION = "table-atomic-facts-arm1-case-v3.2"
REPORT_SCHEMA_VERSION = "table-atomic-facts-arm1-report-v3.2"
MANIFEST_SCHEMA_VERSION = "table-atomic-facts-arm1-evaluation-manifest-v3.2"
INDEX_MANIFEST_SCHEMA_VERSION = "table-atomic-facts-arm1-index-manifest-v3.2"

DEFAULT_AS_OF = "2026-07-18"
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
RERANKER_MAX_LENGTH = 512
RERANKER_THRESHOLD = 0.001
RERANKER_K = 3
SEARCH_TOP_K = 20
RRF_K = 60

DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_FACTS = Path(
    "data/v3/structured/table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_FACT_MANIFEST = Path(
    "data/v3/structured/table_atomic_facts_arm1_manifest_"
    "c173c32935d25b0e3753caa65392eeacf667b01bdc991a6da7aaf5e45fb71666.json"
)
DEFAULT_ENUMERATION = Path(
    "data/v3/evaluation/semantic_requirement_enumeration_"
    "495caba182115c2dbec6e846dca7c0809c4cb8a4de552ee1268440d254d2ba9c.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_RERANK_SCORES = Path(
    "data/v3/evidence/requirement_reranker_scores_"
    "fcecc605fec6c23a03c1aafa66f6a7796c9750f9091d10706485cc4899518e53.jsonl"
)
DEFAULT_ASSEMBLER_CASES = Path(
    "data/v3/evidence/extractive_assembler_v3_chunk_diverse_cases_"
    "06b672aa8775fc1a705005e6d88884000429b3fd0e7c773fc815db3fa1415b2c.jsonl"
)
DEFAULT_ROUTER_CASES = Path(
    "data/v3/router/router_backbone_answer_source_ab_cases_"
    "41e3e5dd351fc3a6ad01113490a835ef380d00d047df71ee39e44603d5fbed39.jsonl"
)
DEFAULT_FALSE_FULL_AUDIT = Path(
    "data/v3/evidence/false_full_case_audit_"
    "c2f0bee2fbcc9e0d8941c47aaa7912429fad62b23c7bf35a3baf6fcbba0d1ec0.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/table_atomic_facts_arm1.md")
DEFAULT_INDEX_DIR = Path("data/v3/indexes")
DEFAULT_EVIDENCE_DIR = Path("data/v3/evidence")
DEFAULT_STRUCTURED_DIR = Path("data/v3/structured")
DEFAULT_REPORT_DIR = Path("reports/v3")

TRANSCENDENCE_SOURCE_CHUNK = (
    "chunk_sha256_44dc7778608597cb03b82b94de29f4cd76f5f93a5e744306b0f24835fa9bede7"
)
TRANSCENDENCE_PROBES = (
    ("transcendence_generic", "초월 가격", ("dnf_game_guide",)),
    (
        "transcendence_unique_oath",
        "서약 결정 초월 유니크 가격",
        ("dnf_game_guide",),
    ),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ratio(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 8) if total else 0.0,
    }


def _iso_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def is_temporally_eligible(fact: dict[str, Any], *, as_of: str) -> bool:
    if not fact["default_exposure"] or fact["review_required"]:
        return False
    if fact["status"] not in {"current", "active", "upcoming"}:
        return False
    current = _iso_day(as_of)
    if current is None:
        raise RuntimeError(f"Invalid as_of: {as_of}")
    valid_from = _iso_day(fact.get("valid_from"))
    valid_to = _iso_day(fact.get("valid_to"))
    if valid_from is not None and valid_from > current:
        return False
    if valid_to is not None and valid_to < current:
        return False
    return True


def is_table_fact_retrievable(
    fact: dict[str, Any],
    *,
    as_of: str,
    time_scope: str = "current",
    allowed_parent_document_ids: frozenset[str] | None = None,
    temporal_by_document: dict[str, dict[str, Any]] | None = None,
) -> bool:
    if (
        allowed_parent_document_ids is not None
        and fact["parent_document_id"] not in allowed_parent_document_ids
    ):
        return False
    if fact["review_required"]:
        return False
    if time_scope != "current":
        return True
    if not is_temporally_eligible(fact, as_of=as_of):
        return False
    if temporal_by_document is None:
        return True
    temporal = temporal_by_document.get(fact["parent_document_id"])
    return temporal is not None and temporal["retrieval_action_current"] != "deny"


def fuse_rankings(
    lexical_ids: list[str], dense_ids: list[str], *, rrf_k: int = RRF_K
) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in (lexical_ids, dense_ids):
        for rank, fact_id in enumerate(ranking, start=1):
            scores[fact_id] += 1.0 / (rrf_k + rank)
    return [
        fact_id
        for fact_id, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def _fact_chunk_adapter(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": fact["fact_id"],
        "parent_document_id": fact["parent_document_id"],
        "parent_content_hash": "table_child",
        "retrieval_text": fact["retrieval_text"],
        "source_id": fact["source_id"],
        "source_kind": fact["source_kind"],
        "status": fact["status"],
        "default_exposure": fact["default_exposure"],
        "review_required": fact["review_required"],
        "offset_source": "table_row_child",
        "valid_from": fact.get("valid_from"),
        "valid_to": fact.get("valid_to"),
    }


def build_sidecar_index(
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    *,
    model: SentenceTransformer,
) -> tuple[dict[str, Any], list[dict[str, Any]], np.ndarray]:
    ordered = sorted(facts, key=lambda row: row["fact_id"])
    adapters = [_fact_chunk_adapter(row) for row in ordered]
    used_parent_ids = {row["parent_document_id"] for row in ordered}
    used_documents = [
        row for row in documents if row["document_id"] in used_parent_ids
    ]
    bm25 = build_bm25_index(adapters, used_documents)
    embeddings = model.encode(
        [row["retrieval_text"] for row in ordered],
        batch_size=16,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    matrix = np.asarray(embeddings, dtype="<f4")
    if matrix.shape[0] != len(ordered) or not np.isfinite(matrix).all():
        raise RuntimeError("Invalid table-child embeddings")
    return bm25, ordered, matrix


def freeze_sidecar_index(
    *,
    root: Path,
    facts_path: Path,
    fact_manifest_path: Path,
    documents_path: Path,
    index_dir: Path,
    structured_dir: Path,
    bm25: dict[str, Any],
    ordered_facts: list[dict[str, Any]],
    embeddings: np.ndarray,
    model_device: str,
) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
    bm25_bytes = _canonical_json_bytes(bm25)
    bm25_sha = _sha256_bytes(bm25_bytes)
    bm25_path = index_dir / f"table_atomic_facts_arm1_bm25_{bm25_sha}.json"
    write_immutable(bm25_path, bm25_bytes)

    metadata_bytes = _serialize_jsonl(ordered_facts, lambda row: row["fact_id"])
    metadata_sha = _sha256_bytes(metadata_bytes)
    metadata_path = index_dir / f"table_atomic_facts_arm1_metadata_{metadata_sha}.jsonl"
    write_immutable(metadata_path, metadata_bytes)

    embedding_bytes = embeddings.tobytes(order="C")
    embedding_sha = _sha256_bytes(embedding_bytes)
    embedding_path = index_dir / f"table_atomic_facts_arm1_embeddings_{embedding_sha}.f32"
    write_immutable(embedding_path, embedding_bytes)

    manifest = {
        "manifest_schema_version": INDEX_MANIFEST_SCHEMA_VERSION,
        "status": "development_only_additive_sidecar_not_promoted",
        "inputs": {
            "facts": {
                "path": facts_path.relative_to(root).as_posix(),
                "sha256": file_sha256(facts_path),
                "row_count": len(ordered_facts),
            },
            "fact_manifest": {
                "path": fact_manifest_path.relative_to(root).as_posix(),
                "sha256": file_sha256(fact_manifest_path),
            },
            "documents": {
                "path": documents_path.relative_to(root).as_posix(),
                "sha256": file_sha256(documents_path),
            },
        },
        "logical_index": {
            "parent_candidates": "frozen_v3.1_candidates_unchanged",
            "row_children": "sidecar_union_only",
            "parent_rank_eviction_possible": False,
        },
        "bm25": {
            "path": bm25_path.relative_to(root).as_posix(),
            "sha256": bm25_sha,
            "row_count": len(ordered_facts),
        },
        "dense": {
            "path": embedding_path.relative_to(root).as_posix(),
            "sha256": embedding_sha,
            "metadata_path": metadata_path.relative_to(root).as_posix(),
            "metadata_sha256": metadata_sha,
            "row_count": embeddings.shape[0],
            "dimension": embeddings.shape[1],
            "dtype": "little_endian_float32",
            "normalized": True,
            "model": EMBEDDING_MODEL,
            "revision": EMBEDDING_REVISION,
            "device": model_device,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = structured_dir / f"table_atomic_facts_arm1_index_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return bm25_path, metadata_path, embedding_path, manifest_path, manifest


def search_sidecar(
    *,
    query: str,
    source_ids: tuple[str, ...],
    bm25: dict[str, Any],
    ordered_facts: list[dict[str, Any]],
    embeddings: np.ndarray,
    query_embedding: np.ndarray,
    top_k: int = SEARCH_TOP_K,
    allowed_parent_document_ids: tuple[str, ...] | None = None,
    time_scope: str = "current",
    as_of: str = DEFAULT_AS_OF,
    temporal_by_document: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not ordered_facts:
        return []
    fact_by_id = {row["fact_id"]: row for row in ordered_facts}
    allowed_parents = (
        frozenset(allowed_parent_document_ids)
        if allowed_parent_document_ids is not None
        else None
    )
    is_allowed = lambda fact: (
        fact["source_id"] in source_ids
        and is_table_fact_retrievable(
            fact,
            as_of=as_of,
            time_scope=time_scope,
            allowed_parent_document_ids=allowed_parents,
            temporal_by_document=temporal_by_document,
        )
    )
    lexical = search_bm25(
        bm25,
        query,
        top_k=len(ordered_facts),
        policy=SearchPolicy(
            default_exposure_only=time_scope == "current",
            allowed_statuses=("current", "active", "upcoming")
            if time_scope == "current"
            else None,
            as_of=as_of if time_scope == "current" else None,
            source_ids=source_ids,
        ),
    )
    lexical_ids = [
        row["chunk_id"]
        for row in lexical
        if is_allowed(fact_by_id[row["chunk_id"]])
    ][:top_k]

    allowed_indices = [
        index
        for index, fact in enumerate(ordered_facts)
        if is_allowed(fact)
    ]
    if allowed_indices:
        scores = embeddings[allowed_indices] @ query_embedding
        dense_order = sorted(
            zip(allowed_indices, scores.tolist(), strict=True),
            key=lambda item: (-float(item[1]), ordered_facts[item[0]]["fact_id"]),
        )[:top_k]
        dense_ids = [ordered_facts[index]["fact_id"] for index, _ in dense_order]
    else:
        dense_ids = []
    fused = fuse_rankings(lexical_ids, dense_ids)[: top_k * 2]
    return [fact_by_id[fact_id] for fact_id in fused]


def select_reranked_children(
    candidates: list[dict[str, Any]], scores: list[float], *, threshold: float, k: int
) -> list[dict[str, Any]]:
    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda item: (-float(item[1]), item[0]["fact_id"]),
    )
    selected = []
    seen_chunks = set()
    for fact, score in ranked:
        if float(score) < threshold or fact["source_chunk_id"] in seen_chunks:
            continue
        seen_chunks.add(fact["source_chunk_id"])
        selected.append({**fact, "reranker_score": round(float(score), 8)})
        if len(selected) == k:
            break
    return selected


def augment_decisions(
    decisions: list[dict[str, Any]],
    selected_by_requirement: dict[int, list[dict[str, Any]]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for index, original in enumerate(decisions, start=1):
        decision = json.loads(json.dumps(original, ensure_ascii=False))
        if decision["status"] != "supported_exact":
            output.append(decision)
            continue
        existing = {span["span_id"] for span in decision["spans"]}
        for fact in selected_by_requirement.get(index, []):
            chunk = chunks_by_id[fact["source_chunk_id"]]
            exact = chunk["display_text"][fact["start_offset"] : fact["end_offset"]]
            if exact != fact["row_text"]:
                raise RuntimeError(f"Atomic row offset mismatch: {fact['fact_id']}")
            if fact["fact_id"] in existing:
                continue
            decision["spans"].append(
                {
                    "span_id": fact["fact_id"],
                    "chunk_id": fact["source_chunk_id"],
                    "start_char": fact["start_offset"],
                    "end_char": fact["end_offset"],
                    "text": exact,
                    "reranker_score": fact["reranker_score"],
                    "row_child": True,
                    "parent_context_required": True,
                }
            )
            existing.add(fact["fact_id"])
        output.append(decision)
    return output


def _summarize_scored(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    docs = [row for row in rows if row["answerability_target"] == "answerable_docs"]
    reject = [row for row in rows if row["answerability_target"] == "reject"]
    realtime = [row for row in rows if row["answerability_target"] == "realtime_api"]
    return {
        "answerable_count": len(docs),
        "grounded": _ratio(sum(row[key]["score"]["grounded_answer"] for row in docs), len(docs)),
        "false_full": _ratio(sum(row[key]["score"]["false_full_answer"] for row in docs), len(docs)),
        "honest_partial": _ratio(sum(row[key]["score"]["honest_partial"] for row in docs), len(docs)),
        "reject_correct": _ratio(sum(row[key]["score"]["reject_correct"] for row in reject), len(reject)),
        "realtime_safe_abstain": _ratio(
            sum(row[key]["score"]["realtime_safe_abstain"] for row in realtime), len(realtime)
        ),
        "realtime_static_exposure": sum(
            row[key]["score"]["realtime_static_exposure"] for row in realtime
        ),
    }


def _candidate_recall(
    cases: list[dict[str, Any]], candidate_key: str
) -> dict[str, Any]:
    total = 0
    hits = 0
    question_total = 0
    question_hits = 0
    for case in cases:
        if not case["evidence_groups"]:
            continue
        present = set(case[candidate_key])
        group_hits = []
        for group in case["evidence_groups"]:
            total += 1
            hit = bool(present & set(group["acceptable_chunk_ids"]))
            hits += hit
            group_hits.append(hit)
        question_total += 1
        question_hits += all(group_hits)
    return {
        "evidence_groups": _ratio(hits, total),
        "all_groups_questions": _ratio(question_hits, question_total),
    }


def _markdown(report: dict[str, Any]) -> str:
    baseline = report["ab_metrics"]["baseline"]
    arm = report["ab_metrics"]["arm1"]
    gate = report["gate"]
    probe = report["transcendence_probe"]
    lines = [
        "# v3.2 Table Row Atomic Facts — Arm 1 A/B",
        "",
        f"Decision: **{gate['decision']}**. This remains development-only and is not promoted.",
        "",
        "## Corpus and integrity",
        "",
        f"- Row-child facts: {report['corpus']['fact_count']:,} facts / {report['corpus']['row_count']:,} rows / {report['corpus']['table_count']:,} tables.",
        f"- Entity identity enrichment: {report['corpus']['facts_with_additional_identity_alias']:,} facts across {report['corpus']['rows_with_additional_identity_alias']:,} rows.",
        f"- Structurally ambiguous matrices quarantined: {report['corpus']['tables_requiring_structural_review']} table / {report['corpus']['facts_requiring_structural_review']} facts.",
        f"- Exact row/value offsets: {report['integrity']['exact_offset_rate']:.2%}; mismatches {report['integrity']['offset_mismatch_count']}.",
        f"- Gold content loss: {report['integrity']['gold_content_loss_count']}; dirty canonical hash unchanged: {report['integrity']['dirty_canonical_hash_unchanged']}.",
        "- Parent candidate ordering is frozen; row children are sidecar-unioned, so parent rank perturbations are structurally zero.",
        "",
        "## Frozen 95 A/B",
        "",
        "| Metric | Dirty baseline | Arm 1 |",
        "|---|---:|---:|",
        f"| Grounded answers | {baseline['grounded']['successes']}/{baseline['grounded']['total']} | {arm['grounded']['successes']}/{arm['grounded']['total']} |",
        f"| False-full | {baseline['false_full']['successes']}/{baseline['false_full']['total']} | {arm['false_full']['successes']}/{arm['false_full']['total']} |",
        f"| Reject correct | {baseline['reject_correct']['successes']}/{baseline['reject_correct']['total']} | {arm['reject_correct']['successes']}/{arm['reject_correct']['total']} |",
        f"| Realtime safe abstain | {baseline['realtime_safe_abstain']['successes']}/{baseline['realtime_safe_abstain']['total']} | {arm['realtime_safe_abstain']['successes']}/{arm['realtime_safe_abstain']['total']} |",
        "",
        f"Candidate recall regressions: {report['candidate_recall']['regression_count']}. New false-full: {report['ab_metrics']['new_false_full_count']}. Temporal leaks: {report['integrity']['temporal_leak_count']}.",
        "",
        "## Transcendence probe",
        "",
        f"Generic `초월 가격` value-row recovery: **{probe['generic_value_row_recovered']}**.",
        f"Generic `초월 가격` complete table views: **{probe['generic_complete_table_count']}**.",
        f"`서약 결정 초월 유니크 가격` all-rarity table recovery: **{probe['oath_all_rarities_recovered']}**.",
        f"Expected frozen source chunk recovered by either probe: **{probe['expected_source_chunk_recovered']}**.",
        "",
    ]
    for item in probe["probes"]:
        lines.extend(
            [
                f"### `{item['query']}`",
                "",
                f"Seed rows: {item['selected_summary'] or 'no eligible row child'}",
                "",
            ]
        )
        if not item["complete_table_views"]:
            lines.extend(["No complete table view was assembled.", ""])
        for table_view in item["complete_table_views"]:
            lines.append(table_view["rendered_markdown"].rstrip())
            lines.append("")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"Frozen sibling-attribute recoveries: {report['ab_metrics']['sibling_attribute_recovered']}/2. Those two audited failures are prose/selection cases, so Arm 1 does not claim to solve them.",
            "Passing this development gate creates only a v3.2 candidate. A new sealed canary is still required before canonical promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate additive table row facts Arm 1")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--fact-manifest", type=Path, default=DEFAULT_FACT_MANIFEST)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--structured-dir", type=Path, default=DEFAULT_STRUCTURED_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")

    root = Path(__file__).resolve().parents[2]
    resolve = lambda value: (root / value).resolve()
    chunks_path = resolve(DEFAULT_CHUNKS)
    documents_path = resolve(DEFAULT_DOCUMENTS)
    facts_path = resolve(args.facts)
    fact_manifest_path = resolve(args.fact_manifest)
    chunks = read_jsonl(chunks_path)
    documents = read_jsonl(documents_path)
    facts = read_jsonl(facts_path)
    chunks_by_id = {row["chunk_id"]: row for row in chunks}

    embedding_model = SentenceTransformer(
        EMBEDDING_MODEL,
        revision=EMBEDDING_REVISION,
        device=args.device,
        local_files_only=True,
    )
    embedding_model.max_seq_length = 512
    bm25, ordered_facts, embeddings = build_sidecar_index(
        facts, documents, model=embedding_model
    )
    index_artifacts = freeze_sidecar_index(
        root=root,
        facts_path=facts_path,
        fact_manifest_path=fact_manifest_path,
        documents_path=documents_path,
        index_dir=resolve(args.index_dir),
        structured_dir=resolve(args.structured_dir),
        bm25=bm25,
        ordered_facts=ordered_facts,
        embeddings=embeddings,
        model_device=args.device,
    )

    evaluation_rows = read_jsonl(resolve(DEFAULT_CANARY)) + read_jsonl(resolve(DEFAULT_DEV))
    evaluation_by_id = {row["dev_id"]: row for row in evaluation_rows}
    enumeration_by_id = {row["case_id"]: row for row in read_jsonl(resolve(DEFAULT_ENUMERATION))}
    score_by_id = {row["case_id"]: row for row in read_jsonl(resolve(DEFAULT_RERANK_SCORES))}
    assembler_by_id = {row["case_id"]: row for row in read_jsonl(resolve(DEFAULT_ASSEMBLER_CASES))}
    router_by_id = {row["case_id"]: row for row in read_jsonl(resolve(DEFAULT_ROUTER_CASES))}
    if not all(len(rows) == 95 for rows in (evaluation_by_id, enumeration_by_id, score_by_id, assembler_by_id, router_by_id)):
        raise RuntimeError("Arm 1 requires the exact frozen 95-case joins")

    requests = []
    case_material = []
    all_queries = []
    for case_id in sorted(evaluation_by_id):
        evaluation = evaluation_by_id[case_id]
        requirements = enumeration_by_id[case_id]["requirements"]
        decisions = assembler_by_id[case_id]["decisions"]
        score_requirements = score_by_id[case_id]["requirements"]
        if len(requirements) != len(decisions) or len(requirements) != len(score_requirements):
            raise RuntimeError(f"Requirement join mismatch: {case_id}")
        baseline_candidates = sorted(
            {
                candidate["chunk_id"]
                for row in score_requirements
                for candidate in row["candidates"]
            }
        )
        candidate_sources = tuple(
            sorted(
                {
                    chunks_by_id[chunk_id]["source_id"]
                    for chunk_id in baseline_candidates
                }
            )
        )
        case_material.append(
            {
                "case_id": case_id,
                "dataset": router_by_id[case_id]["dataset"],
                "question": evaluation["question"],
                "answerability_target": router_by_id[case_id]["answerability_target"],
                "requirements": requirements,
                "evidence_groups": evaluation["evidence_groups"],
                "baseline_decisions": decisions,
                "baseline_candidate_chunk_ids": baseline_candidates,
                "candidate_sources": candidate_sources,
            }
        )
        for index, (requirement, decision) in enumerate(zip(requirements, decisions, strict=True), start=1):
            if decision["status"] != "supported_exact":
                continue
            query = requirement_text(requirement)
            all_queries.append(query)
            requests.append(
                {
                    "request_id": f"{case_id}:{index}",
                    "case_id": case_id,
                    "requirement_index": index,
                    "query": query,
                    "source_ids": candidate_sources,
                }
            )
    for probe_id, query, source_ids in TRANSCENDENCE_PROBES:
        all_queries.append(query)
        requests.append(
            {
                "request_id": f"probe:{probe_id}",
                "case_id": None,
                "requirement_index": None,
                "query": query,
                "source_ids": source_ids,
            }
        )

    unique_queries = sorted(set(all_queries))
    query_vectors = embedding_model.encode(
        unique_queries,
        batch_size=16,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    query_by_text = {
        query: np.asarray(vector, dtype=np.float32)
        for query, vector in zip(unique_queries, query_vectors, strict=True)
    }
    for request in requests:
        request["candidates"] = search_sidecar(
            query=request["query"],
            source_ids=tuple(request["source_ids"]),
            bm25=bm25,
            ordered_facts=ordered_facts,
            embeddings=embeddings,
            query_embedding=query_by_text[request["query"]],
        )

    pairs = [
        (request["query"], fact["retrieval_text"])
        for request in requests
        for fact in request["candidates"]
    ]
    reranker = CrossEncoder(
        RERANKER_MODEL,
        revision=RERANKER_REVISION,
        max_length=RERANKER_MAX_LENGTH,
        device=args.device,
        local_files_only=True,
    )
    raw_scores = reranker.predict(
        pairs,
        batch_size=4,
        show_progress_bar=True,
        convert_to_numpy=True,
    ) if pairs else np.asarray([], dtype=np.float32)
    raw_scores = np.asarray(raw_scores, dtype=np.float64).reshape(-1)
    if len(raw_scores) != len(pairs) or not np.isfinite(raw_scores).all():
        raise RuntimeError("Invalid row-child reranker scores")
    cursor = 0
    for request in requests:
        count = len(request["candidates"])
        scores = raw_scores[cursor : cursor + count].tolist()
        cursor += count
        request["selected"] = select_reranked_children(
            request["candidates"],
            scores,
            threshold=RERANKER_THRESHOLD,
            k=RERANKER_K,
        )

    requests_by_case: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for request in requests:
        if request["case_id"] is not None:
            requests_by_case[request["case_id"]][request["requirement_index"]] = request

    chunk_to_parent = {row["chunk_id"]: row["parent_document_id"] for row in chunks}
    result_rows = []
    for case in case_material:
        selected_by_requirement = {
            index: request["selected"]
            for index, request in requests_by_case.get(case["case_id"], {}).items()
        }
        arm_decisions = augment_decisions(
            case["baseline_decisions"], selected_by_requirement, chunks_by_id
        )
        baseline_supported = {
            index
            for index, decision in enumerate(case["baseline_decisions"], start=1)
            if decision["status"] == "supported_exact"
        }
        arms = {}
        for name, decisions in (
            ("baseline", case["baseline_decisions"]),
            ("arm1", arm_decisions),
        ):
            arm = simulate_arm(
                placement="arm0",
                question=case["question"],
                assembler_decisions=decisions,
                classifier_predictions=[],
                chunk_to_parent=chunk_to_parent,
            )
            arms[name] = {
                **arm,
                "score": _score_arm(
                    arm,
                    target=case["answerability_target"],
                    evidence_groups=case["evidence_groups"],
                    expected_docs_flags=[True] * len(case["requirements"]),
                    baseline_supported_indices=baseline_supported,
                ),
            }
        child_candidate_ids = sorted(
            {
                fact["source_chunk_id"]
                for request in requests_by_case.get(case["case_id"], {}).values()
                for fact in request["candidates"]
            }
        )
        selected_children = [
            {
                "requirement_index": index,
                "query": request["query"],
                "candidate_fact_count": len(request["candidates"]),
                "selected": [
                    {
                        key: fact[key]
                        for key in (
                            "fact_id",
                            "source_chunk_id",
                            "subject",
                            "attribute",
                            "value",
                            "row_text",
                            "start_offset",
                            "end_offset",
                            "reranker_score",
                        )
                    }
                    for fact in request["selected"]
                ],
            }
            for index, request in sorted(requests_by_case.get(case["case_id"], {}).items())
        ]
        result_rows.append(
            {
                "case_schema_version": CASE_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "dataset": case["dataset"],
                "answerability_target": case["answerability_target"],
                "evidence_groups": case["evidence_groups"],
                "baseline_candidate_chunk_ids": case["baseline_candidate_chunk_ids"],
                "arm1_candidate_chunk_ids": sorted(
                    set(case["baseline_candidate_chunk_ids"]) | set(child_candidate_ids)
                ),
                "baseline": arms["baseline"],
                "arm1": arms["arm1"],
                "row_children": selected_children,
                "gold_ids_used_for_scoring_only": True,
                "gold_ids_available_to_retrieval_or_reranker": False,
                "parent_candidate_order_changed": False,
            }
        )
    result_rows.sort(key=lambda row: (row["dataset"], row["case_id"]))

    baseline_metrics = _summarize_scored(result_rows, "baseline")
    arm_metrics = _summarize_scored(result_rows, "arm1")
    expected_frozen = {
        "answerable_count": 82,
        "grounded": 73,
        "false_full": 9,
        "reject": 11,
        "realtime_safe": 2,
    }
    observed = {
        "answerable_count": baseline_metrics["answerable_count"],
        "grounded": baseline_metrics["grounded"]["successes"],
        "false_full": baseline_metrics["false_full"]["successes"],
        "reject": baseline_metrics["reject_correct"]["successes"],
        "realtime_safe": baseline_metrics["realtime_safe_abstain"]["successes"],
    }
    if observed != expected_frozen:
        raise RuntimeError(f"Frozen baseline reproduction failed: {observed}")

    baseline_false = {
        row["case_id"] for row in result_rows if row["baseline"]["score"]["false_full_answer"]
    }
    arm_false = {
        row["case_id"] for row in result_rows if row["arm1"]["score"]["false_full_answer"]
    }
    false_audit = read_jsonl(resolve(DEFAULT_FALSE_FULL_AUDIT))
    sibling_ids = {
        row["case_id"]
        for row in false_audit
        if row["classification"] == "A_WRONG_ATTRIBUTE"
    }
    baseline_recall = _candidate_recall(result_rows, "baseline_candidate_chunk_ids")
    arm_recall = _candidate_recall(result_rows, "arm1_candidate_chunk_ids")
    recall_regressions = sum(
        bool(
            set(row["baseline_candidate_chunk_ids"])
            & set(group["acceptable_chunk_ids"])
        )
        and not bool(
            set(row["arm1_candidate_chunk_ids"])
            & set(group["acceptable_chunk_ids"])
        )
        for row in result_rows
        for group in row["evidence_groups"]
    )

    selected_facts = [
        fact
        for request in requests
        if request["case_id"] is not None
        for fact in request["selected"]
    ]
    replacement_character_count = sum(
        value.count("\ufffd")
        for fact in ordered_facts
        for value in (
            fact["table_caption"],
            fact["subject"],
            fact["retrieval_text"],
        )
    )
    exact_mismatches = sum(
        chunks_by_id[fact["source_chunk_id"]]["display_text"][
            fact["start_offset"] : fact["end_offset"]
        ]
        != fact["row_text"]
        for fact in selected_facts
    )
    temporal_leaks = sum(
        not is_temporally_eligible(fact, as_of=DEFAULT_AS_OF)
        for fact in selected_facts
    )
    all_gold_ids = {
        chunk_id
        for row in result_rows
        for group in row["evidence_groups"]
        for chunk_id in group["acceptable_chunk_ids"]
    }
    gold_id_loss = len(all_gold_ids - set(chunks_by_id))

    probe_rows = []
    for request in requests:
        if not request["request_id"].startswith("probe:"):
            continue
        selected = request["selected"]
        complete_table_views = assemble_table_group_answers(
            query=request["query"],
            ranked_seed_facts=selected,
            all_facts=ordered_facts,
            chunks_by_id=chunks_by_id,
        )
        probe_rows.append(
            {
                "probe_id": request["request_id"].split(":", 1)[1],
                "query": request["query"],
                "candidate_count": len(request["candidates"]),
                "selected_fact_ids": [row["fact_id"] for row in selected],
                "selected_source_chunk_ids": [row["source_chunk_id"] for row in selected],
                "selected_summary": "; ".join(
                    f"{row['subject']} — {row['attribute']} — {row['value']}"
                    for row in selected
                ),
                "value_row_recovered": any(
                    row["value"] and any(character.isdigit() for character in row["value"])
                    for row in selected
                ),
                "complete_table_views": complete_table_views,
            }
        )
    generic_probe = next(row for row in probe_rows if row["probe_id"] == "transcendence_generic")
    oath_probe = next(
        row for row in probe_rows if row["probe_id"] == "transcendence_unique_oath"
    )
    oath_views = [
        view
        for view in oath_probe["complete_table_views"]
        if "서약 결정 초월" in f"{view['caption']} {view['table_subject']}"
    ]
    oath_required_rarities = {"유니크", "레전더리", "에픽", "태초"}
    oath_required_attributes = {
        "광휘의 소울",
        "상급 원소 결정",
        "순례의 인장 / 골드",
        "솔리드 소울",
    }
    oath_all_rarities_recovered = len(oath_views) == 1 and (
        oath_required_rarities
        <= {row["label"] for row in oath_views[0]["rows"]}
        and oath_required_attributes <= set(oath_views[0]["attributes"])
        and oath_views[0]["exact_offset_mismatch_count"] == 0
    )
    expected_source_recovered = any(
        TRANSCENDENCE_SOURCE_CHUNK in row["selected_source_chunk_ids"] for row in probe_rows
    )

    fact_manifest = json.loads(fact_manifest_path.read_text(encoding="utf-8"))
    gate_checks = {
        "gold_content_loss_zero": gold_id_loss == 0,
        "exact_offset_100_percent": exact_mismatches == 0,
        "candidate_recall_nonregression": recall_regressions == 0,
        "grounded_at_least_73": arm_metrics["grounded"]["successes"] >= 73,
        "new_false_full_zero": len(arm_false - baseline_false) == 0,
        "temporal_leak_zero": temporal_leaks == 0,
        "transcendence_value_row_recovered": generic_probe["value_row_recovered"],
        "transcendence_oath_all_rarities_recovered": oath_all_rarities_recovered,
        "replacement_character_zero": replacement_character_count == 0,
    }
    gate_pass = all(gate_checks.values())

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "status": "development_only_not_promoted",
        "corpus": {
            "facts_sha256": file_sha256(facts_path),
            "fact_count": fact_manifest["audit"]["fact_count"],
            "row_count": fact_manifest["audit"]["row_count"],
            "table_count": fact_manifest["audit"]["table_count"],
            "target_tables": fact_manifest["audit"]["target_tables"],
            "complete_tables_seen": fact_manifest["audit"]["complete_tables_seen"],
            "rows_with_additional_identity_alias": fact_manifest["audit"].get(
                "rows_with_additional_identity_alias", 0
            ),
            "facts_with_additional_identity_alias": fact_manifest["audit"].get(
                "facts_with_additional_identity_alias", 0
            ),
            "tables_requiring_structural_review": fact_manifest["audit"].get(
                "tables_requiring_structural_review", 0
            ),
            "facts_requiring_structural_review": fact_manifest["audit"].get(
                "facts_requiring_structural_review", 0
            ),
        },
        "configuration": {
            "parent_candidate_behavior": "frozen_unchanged_sidecar_union",
            "child_search": "bm25_bge_m3_rrf",
            "search_top_k_per_channel": SEARCH_TOP_K,
            "rrf_k": RRF_K,
            "reranker": RERANKER_MODEL,
            "reranker_revision": RERANKER_REVISION,
            "reranker_threshold": RERANKER_THRESHOLD,
            "reranker_k_distinct_source_chunks": RERANKER_K,
            "table_group_assembler": TABLE_GROUP_ASSEMBLER_VERSION,
            "table_group_behavior": "seed_then_expand_complete_table_without_global_k_change",
            "assembler_llm_calls": 0,
            "training_runs": 0,
        },
        "ab_metrics": {
            "baseline": baseline_metrics,
            "arm1": arm_metrics,
            "recovered_false_full_count": len(baseline_false - arm_false),
            "new_false_full_count": len(arm_false - baseline_false),
            "recovered_false_full_ids": sorted(baseline_false - arm_false),
            "new_false_full_ids": sorted(arm_false - baseline_false),
            "sibling_attribute_recovered": len(sibling_ids & (baseline_false - arm_false)),
            "sibling_attribute_total": len(sibling_ids),
            "selected_row_child_fact_count": len(selected_facts),
            "selected_row_child_question_count": len(
                {
                    request["case_id"]
                    for request in requests
                    if request["case_id"] is not None and request["selected"]
                }
            ),
        },
        "candidate_recall": {
            "baseline": baseline_recall,
            "arm1": arm_recall,
            "regression_count": recall_regressions,
            "parent_rank_perturbation_count": 0,
        },
        "integrity": {
            "dirty_canonical_expected_sha256": DEFAULT_CHUNKS.stem.rsplit("_", 1)[-1],
            "dirty_canonical_observed_sha256": file_sha256(chunks_path),
            "dirty_canonical_hash_unchanged": file_sha256(chunks_path)
            == DEFAULT_CHUNKS.stem.rsplit("_", 1)[-1],
            "gold_content_loss_count": gold_id_loss,
            "selected_offset_check_count": len(selected_facts),
            "offset_mismatch_count": exact_mismatches,
            "exact_offset_rate": round(
                (len(selected_facts) - exact_mismatches) / len(selected_facts), 8
            )
            if selected_facts
            else 1.0,
            "temporal_leak_count": temporal_leaks,
            "replacement_character_count": replacement_character_count,
        },
        "transcendence_probe": {
            "generic_value_row_recovered": generic_probe["value_row_recovered"],
            "generic_complete_table_count": len(generic_probe["complete_table_views"]),
            "oath_all_rarities_recovered": oath_all_rarities_recovered,
            "oath_required_rarities": sorted(oath_required_rarities),
            "oath_required_attributes": sorted(oath_required_attributes),
            "expected_source_chunk": TRANSCENDENCE_SOURCE_CHUNK,
            "expected_source_chunk_recovered": expected_source_recovered,
            "probes": probe_rows,
            "benchmark_metric": False,
        },
        "gate": {
            "checks": gate_checks,
            "pass": gate_pass,
            "decision": "GO_V3_2_CANONICAL_CANDIDATE_ONLY_SEALED_CANARY_REQUIRED"
            if gate_pass
            else "NO_GO_DIRTY_CANONICAL_REMAINS",
            "promoted": False,
            "next_required_gate": "new_sealed_canary" if gate_pass else None,
        },
    }

    cases_bytes = _serialize_jsonl(result_rows, lambda row: (row["dataset"], row["case_id"]))
    cases_sha = _sha256_bytes(cases_bytes)
    cases_path = resolve(args.evidence_dir) / f"table_atomic_facts_arm1_ab_cases_{cases_sha}.jsonl"
    write_immutable(cases_path, cases_bytes)
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = resolve(args.report_dir) / f"table_atomic_facts_arm1_ab_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = resolve(args.report_dir) / f"table_atomic_facts_arm1_ab_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    index_manifest_path = index_artifacts[3]
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "development_only_not_promoted",
        "inputs": {
            "dirty_chunks": {"path": DEFAULT_CHUNKS.as_posix(), "sha256": file_sha256(chunks_path)},
            "facts": {"path": args.facts.as_posix(), "sha256": file_sha256(facts_path)},
            "fact_manifest": {"path": args.fact_manifest.as_posix(), "sha256": file_sha256(fact_manifest_path)},
            "enumeration": {"path": DEFAULT_ENUMERATION.as_posix(), "sha256": file_sha256(resolve(DEFAULT_ENUMERATION))},
            "canary": {"path": DEFAULT_CANARY.as_posix(), "sha256": file_sha256(resolve(DEFAULT_CANARY))},
            "dev": {"path": DEFAULT_DEV.as_posix(), "sha256": file_sha256(resolve(DEFAULT_DEV))},
            "rerank_scores": {"path": DEFAULT_RERANK_SCORES.as_posix(), "sha256": file_sha256(resolve(DEFAULT_RERANK_SCORES))},
            "assembler_cases": {"path": DEFAULT_ASSEMBLER_CASES.as_posix(), "sha256": file_sha256(resolve(DEFAULT_ASSEMBLER_CASES))},
            "router_cases": {"path": DEFAULT_ROUTER_CASES.as_posix(), "sha256": file_sha256(resolve(DEFAULT_ROUTER_CASES))},
            "contract": {"path": DEFAULT_CONTRACT.as_posix(), "sha256": file_sha256(resolve(DEFAULT_CONTRACT))},
            "evaluator_source": {
                "path": Path(__file__).resolve().relative_to(root).as_posix(),
                "sha256": file_sha256(Path(__file__).resolve()),
            },
            "table_group_assembler_source": {
                "path": "src/v3/assemble_table_group_answers.py",
                "sha256": file_sha256(resolve(Path("src/v3/assemble_table_group_answers.py"))),
            },
        },
        "artifacts": {
            "sidecar_index_manifest": {"path": index_manifest_path.relative_to(root).as_posix(), "sha256": file_sha256(index_manifest_path)},
            "cases": {"path": cases_path.relative_to(root).as_posix(), "sha256": cases_sha, "row_count": len(result_rows)},
            "report": {"path": report_path.relative_to(root).as_posix(), "sha256": report_sha},
            "report_markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "model": {
            "embedding": {"name": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION},
            "reranker": {"name": RERANKER_MODEL, "revision": RERANKER_REVISION, "max_length": RERANKER_MAX_LENGTH},
            "device": args.device,
        },
        "gate": report["gate"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = resolve(args.structured_dir) / f"table_atomic_facts_arm1_evaluation_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    print(
        json.dumps(
            {
                "report": report_path.relative_to(root).as_posix(),
                "report_markdown": markdown_path.relative_to(root).as_posix(),
                "cases": cases_path.relative_to(root).as_posix(),
                "manifest": manifest_path.relative_to(root).as_posix(),
                "index_manifest": index_manifest_path.relative_to(root).as_posix(),
                "gate": report["gate"],
                "ab_metrics": report["ab_metrics"],
                "transcendence_probe": report["transcendence_probe"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
