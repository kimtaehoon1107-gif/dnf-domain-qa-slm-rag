from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


RUNNER_VERSION = "simple-rag-minimal-verifier-new-claim32-paired-ab-v1"
DEFAULT_SEALED = Path(
    "data/v3/evaluation/"
    "typed_evidence_ref_new_claim32_sealed_"
    "b8e9f67bc3cb927168f312d3cb5dfaca154c2dffd14c7fabd8c6efb5a98ee83a.jsonl"
)
DEFAULT_TABLE_FACTS = Path(
    "data/v3/structured/table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "simple_rag_minimal_verifier_b134_new_claim32_paired_20260728.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "simple_rag_minimal_verifier_b134_new_claim32_paired_20260728.json"
)


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compatible_reviewed(row: dict[str, Any]) -> dict[str, Any]:
    groups = []
    for index, requirement in enumerate(row["requirements"], 1):
        units = requirement["acceptable_evidence_units"]
        groups.append(
            {
                "group_id": f"evidence_{index}",
                "requirement_id": requirement["requirement_id"],
                "acceptable_chunk_ids": list(
                    dict.fromkeys(unit["chunk_id"] for unit in units)
                ),
                "document_ids": list(
                    dict.fromkeys(unit["document_id"] for unit in units)
                ),
                "evidence_span": (
                    units[0]["text"] if units else "__UNSUPPORTED__"
                ),
                "expected_evidence": units,
            }
        )
    return {
        **row,
        "evidence_groups": groups,
        "expected_requirement_count": len(row["requirements"]),
    }


def _adapt(
    sealed: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    source_decisions = result.get("requirements") or []
    source_audits = (
        result.get("verification", {}).get("requirements") or []
    )
    decisions = []
    audits = []
    for index, requirement in enumerate(sealed["requirements"]):
        source = source_decisions[index] if index < len(source_decisions) else {}
        decisions.append(
            {
                "requirement_id": requirement["requirement_id"],
                "question_part": source.get("question_part"),
                "status": source.get("status", "unsupported"),
                "answer": source.get("answer", ""),
                "citations": source.get("citations") or [],
            }
        )
        audit = source_audits[index] if index < len(source_audits) else {}
        audits.append(
            {
                "requirement_id": requirement["requirement_id"],
                "model_status": audit.get("model_status"),
                "exposed_status": decisions[-1]["status"],
                "failure_reasons": audit.get(
                    "failure_reasons",
                    (
                        ["model_requirement_missing"]
                        if index >= len(source_decisions)
                        else []
                    ),
                ),
            }
        )
    return {
        "question_time_scope": result.get("question_time_scope"),
        "model_response_mode": result.get("model_response_mode"),
        "response_mode": result.get("response_mode", "abstain"),
        "requirements": decisions,
        "rendered_answer": result.get("rendered_answer", ""),
        "verification": {
            **result.get("verification", {}),
            "requirements": audits,
        },
    }


def _apply_existing_guards(
    result: dict[str, Any],
    *,
    question: str,
    chunks_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    guard: Any,
) -> dict[str, Any]:
    guarded = guard.apply_subject_period_identity_guard(
        result,
        question=question,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
    )
    guarded = guard.apply_relation_value_colocation_guard(
        guarded,
        question=question,
    )
    return guard.apply_temporal_role_guard(
        guarded,
        question=question,
        chunks_by_id=chunks_by_id,
        documents_by_id=documents_by_id,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, round((len(ordered) - 1) * fraction)),
    )
    return round(ordered[index], 3)


def _freeze_candidate(
    *,
    root: Path,
    source_root: Path,
    legacy_source_commit: str,
    model: str,
    model_digest: str,
    sealed_path: Path,
    table_facts_path: Path,
    retrieval_inputs: dict[str, Path],
    retrieval_provenance: dict[str, Any],
    evaluation_role: str,
) -> tuple[Path, dict[str, Any]]:
    payload = {
        "manifest_version": "simple-rag-minimal-verifier-freeze-v1",
        "candidate_name": "simple-rag-v2-plus-b1-b3-b4",
        "evaluation_role": evaluation_role,
        "base_pipeline": {
            "legacy_source_commit": legacy_source_commit,
            "simple_rag_version": "dnf-simple-domain-rag-v2",
            "model": model,
            "model_digest": model_digest,
            "retrieval_depth": 20,
            "rerank_depth": 5,
        },
        "included_stages": [
            "B1_v2_table_subject_attribute_value_guard",
            "B3_unique_whitespace_quote_recovery",
            "B4_v2_normalized_factual_value_verifier",
        ],
        "excluded_stages": [
            "B2_server_scope_agreement_guard",
            "B5_prompt_compaction",
        ],
        "input_sha256": {
            "sealed_32": _file_sha256(sealed_path),
            "table_atomic_facts": _file_sha256(table_facts_path),
            "minimal_verifier_source": _file_sha256(
                root / "src/v3/simple_rag_minimal_verifier.py"
            ),
            "incremental_guards_source": _file_sha256(
                root / "src/v3/simple_rag_incremental_guards.py"
            ),
            "legacy_simple_rag_source": _file_sha256(
                source_root / "src/v3/simple_domain_rag.py"
            ),
            **{
                name: _file_sha256(path)
                for name, path in retrieval_inputs.items()
            },
        },
        "retrieval_provenance": retrieval_provenance,
        "mutation_after_freeze_allowed": False,
    }
    candidate_sha256 = _canonical_sha256(payload)
    manifest = {**payload, "candidate_sha256": candidate_sha256}
    path = (
        root
        / "data/v3/evaluation"
        / (
            "simple_rag_minimal_verifier_b134_candidate_manifest_"
            f"{candidate_sha256}.json"
        )
    )
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise RuntimeError("existing candidate manifest content mismatch")
    else:
        path.write_text(encoded, encoding="utf-8")
    return path, manifest


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    source_root = args.legacy_source_root.resolve()
    helper_path = root / "src/v3/simple_rag_minimal_verifier.py"
    helper = _load_module(
        helper_path,
        "_simple_rag_minimal_verifier_new_claim32",
    )

    root_text = os.path.normcase(str(root))
    sys.path = [
        str(source_root),
        *[
            entry
            for entry in sys.path
            if os.path.normcase(str(Path(entry or ".").resolve()))
            != root_text
        ],
    ]
    guard = _load_module(
        root / "src/v3/simple_rag_incremental_guards.py",
        "_simple_rag_incremental_guards_new_claim32",
    )

    from src.io_utils import read_jsonl, write_jsonl
    from src.v3.evaluate_grounded_llm_replay import score_verified_output
    from src.v3.evaluate_simple_domain_rag import summarize_cases
    from src.v3.generate_grounded_llm_answer import (
        GroundedAnswerOutput,
        SYSTEM_INSTRUCTIONS,
        build_grounded_prompt,
        safe_abstention,
        verify_and_sanitize_output,
    )
    from src.v3.retrieve_v3 import (
        DEFAULT_BM25_MANIFEST,
        DEFAULT_CHUNKS,
        DEFAULT_DENSE_MANIFEST,
        DEFAULT_DOCUMENTS,
    )
    from src.v3.score_typed_evidence_ref_generalization import (
        score_generalization_cases,
    )
    from src.v3.simple_domain_rag import (
        DEFAULT_AS_OF,
        SIMPLE_RAG_VERSION,
        SimpleDomainRAG,
        enforce_factual_token_support,
    )

    if SIMPLE_RAG_VERSION != "dnf-simple-domain-rag-v2":
        raise RuntimeError(
            f"expected frozen v2 source, got {SIMPLE_RAG_VERSION}"
        )

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    sealed_path = resolve(args.sealed)
    table_facts_path = resolve(args.table_facts)
    output_path = resolve(args.output)
    summary_path = resolve(args.summary)
    sealed_rows = read_jsonl(sealed_path)
    if len(sealed_rows) != 32:
        raise RuntimeError("paired new-claim comparison requires 32 rows")
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("paired A/B output already exists")

    os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    rag = SimpleDomainRAG(
        root=root,
        model=args.model,
        device=args.device,
        retrieval_depth=20,
        rerank_depth=5,
        timeout=args.timeout_seconds,
    )
    rag._initialize()
    assert rag._artifacts is not None
    chunks_by_id = rag._artifacts.chunks_by_id
    documents_by_id = rag._artifacts.documents_by_id
    retrieval_inputs = {
        "bm25_manifest": resolve(DEFAULT_BM25_MANIFEST),
        "dense_manifest": resolve(DEFAULT_DENSE_MANIFEST),
        "chunks": resolve(DEFAULT_CHUNKS),
        "documents": resolve(DEFAULT_DOCUMENTS),
    }
    manifest_path, manifest = _freeze_candidate(
        root=root,
        source_root=source_root,
        legacy_source_commit=args.legacy_source_commit,
        model=args.model,
        model_digest=args.model_digest,
        sealed_path=sealed_path,
        table_facts_path=table_facts_path,
        retrieval_inputs=retrieval_inputs,
        retrieval_provenance=rag._artifacts.provenance,
        evaluation_role=args.evaluation_role,
    )
    table_rows_by_chunk = helper.build_table_rows_by_chunk(
        read_jsonl(table_facts_path),
        chunks_by_id=chunks_by_id,
    )
    generator = helper.ObservedGroundedGenerator(
        output_schema=GroundedAnswerOutput,
        system_instructions=SYSTEM_INSTRUCTIONS,
    )

    rows = []
    started = time.perf_counter()
    for current, sealed in enumerate(sealed_rows, 1):
        question = sealed["question_text"]
        call_started = time.perf_counter()
        routed, selected = rag._retrieve_and_rerank(question)
        candidate_ids = [item["chunk_id"] for item in selected]
        prompt = build_grounded_prompt(
            question=question,
            as_of=DEFAULT_AS_OF,
            candidate_chunk_ids=candidate_ids,
            chunks_by_id=chunks_by_id,
            documents_by_id=documents_by_id,
            temporal_by_document=rag.temporal_by_document,
        )
        quote_recovery = []
        try:
            generated = generator(
                prompt=prompt,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
            )
            raw_output = copy.deepcopy(generated["output"])
            original_verified = verify_and_sanitize_output(
                raw_output,
                candidate_chunk_ids=candidate_ids,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                temporal_by_document=rag.temporal_by_document,
            )
            original_checked = enforce_factual_token_support(
                original_verified
            )
            original = _apply_existing_guards(
                original_checked,
                question=question,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                guard=guard,
            )

            recovered_raw, quote_recovery = (
                helper.recover_unique_whitespace_quotes(
                    raw_output,
                    candidate_chunk_ids=candidate_ids,
                    chunks_by_id=chunks_by_id,
                )
            )
            candidate_verified = verify_and_sanitize_output(
                recovered_raw,
                candidate_chunk_ids=candidate_ids,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                temporal_by_document=rag.temporal_by_document,
            )
            candidate_checked = helper.enforce_normalized_factual_support(
                candidate_verified,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
            )
            candidate = _apply_existing_guards(
                candidate_checked,
                question=question,
                chunks_by_id=chunks_by_id,
                documents_by_id=documents_by_id,
                guard=guard,
            )
            candidate = helper.apply_table_attribute_identity_guard(
                candidate,
                question=question,
                table_rows_by_chunk=table_rows_by_chunk,
            )
            generation_error = None
        except Exception as exc:
            raw_output = generator.last.get("output")
            original = safe_abstention(exc)
            candidate = copy.deepcopy(original)
            generation_error = f"{type(exc).__name__}: {exc}"

        reviewed = _compatible_reviewed(sealed)
        scores = {
            stage: score_verified_output(
                reviewed,
                candidate_chunk_ids=candidate_ids,
                verified=result,
                chunks_by_id=chunks_by_id,
            )
            for stage, result in {
                "original": original,
                "frozen_b134": candidate,
            }.items()
        }
        row = {
            "runner_version": RUNNER_VERSION,
            "evaluation_role": (
                "paired_adaptive_new_claim32_ab_not_generalization"
            ),
            "candidate_manifest": manifest_path.relative_to(root).as_posix(),
            "candidate_sha256": manifest["candidate_sha256"],
            "candidate_id": sealed["candidate_id"],
            "slot_ordinal": sealed["slot_ordinal"],
            "question_text": question,
            "source_id": sealed["source_id"],
            "candidate_chunk_ids": candidate_ids,
            "raw_model_output": raw_output,
            "quote_recovery": quote_recovery,
            "original_result": original,
            "frozen_b134_result": candidate,
            "strict_scores": scores,
            "route": routed.get("route"),
            "generation_error": generation_error,
            "observability": {
                **generator.last,
                "prompt": None,
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest(),
            },
            "pipeline_latency_ms": round(
                (time.perf_counter() - call_started) * 1000,
                3,
            ),
        }
        rows.append(row)
        write_jsonl(output_path, rows)
        print(
            json.dumps(
                {
                    "progress": f"{current}/32",
                    "slot": sealed["slot_ordinal"],
                    "original_mode": original["response_mode"],
                    "frozen_mode": candidate["response_mode"],
                    "changed": original != candidate,
                    "finish_reason": generator.last.get("finish_reason"),
                    "generation_error": generation_error,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    stages = {}
    for stage, field in (
        ("original", "original_result"),
        ("frozen_b134", "frozen_b134_result"),
    ):
        cases = []
        strict_cases = []
        for sealed, row in zip(sealed_rows, rows):
            result = row[field]
            cases.append(
                {
                    "candidate_id": row["candidate_id"],
                    "slot_ordinal": row["slot_ordinal"],
                    "question_text": row["question_text"],
                    "verified_output": _adapt(sealed, result),
                    "requirement_candidate_chunk_ids": [
                        list(row["candidate_chunk_ids"])
                        for _ in sealed["requirements"]
                    ],
                    "model_call": {
                        "call_count": int(not row["generation_error"]),
                        "latency_ms": float(
                            row["observability"].get("latency_ms") or 0.0
                        ),
                        "usage": row["observability"].get("usage") or {},
                    },
                }
            )
            strict_cases.append(
                {
                    "candidate_id": row["candidate_id"],
                    "slot_ordinal": row["slot_ordinal"],
                    "is_table_source": row["source_id"]
                    in {"dnf_monthly_item", "dnf_seria_shop"},
                    "gold_requirement_count": len(sealed["requirements"]),
                    "score": row["strict_scores"][stage],
                    "result": result,
                }
            )
        _, fixed_summary = score_generalization_cases(
            sealed_rows,
            copy.deepcopy(cases),
            chunks_by_id=chunks_by_id,
        )
        stages[stage] = {
            "conventional_strict": summarize_cases(strict_cases),
            "fixed_gold_value_scoring": fixed_summary,
            "response_modes": dict(
                sorted(
                    Counter(row[field]["response_mode"] for row in rows).items()
                )
            ),
        }

    generation_latencies = [
        float(row["observability"].get("latency_ms") or 0.0)
        for row in rows
    ]
    pipeline_latencies = [
        float(row["pipeline_latency_ms"]) for row in rows
    ]
    summary = {
        "runner_version": RUNNER_VERSION,
        "evaluation_role": args.evaluation_role,
        "candidate_manifest": manifest_path.relative_to(root).as_posix(),
        "candidate_sha256": manifest["candidate_sha256"],
        "model": args.model,
        "model_digest": args.model_digest,
        "legacy_source_commit": args.legacy_source_commit,
        "sealed_sha256": _file_sha256(sealed_path),
        "retrieval_calls": 32,
        "generation_calls": sum(
            not row["generation_error"] for row in rows
        ),
        "generation_errors": [
            {
                "slot_ordinal": row["slot_ordinal"],
                "error": row["generation_error"],
                "finish_reason": row["observability"].get("finish_reason"),
            }
            for row in rows
            if row["generation_error"]
        ],
        "quote_recovery_slots": [
            row["slot_ordinal"] for row in rows if row["quote_recovery"]
        ],
        "changed_slots": [
            row["slot_ordinal"]
            for row in rows
            if row["original_result"] != row["frozen_b134_result"]
        ],
        "latency_ms": {
            "generation_mean": round(
                statistics.mean(generation_latencies),
                3,
            ),
            "generation_p50": round(
                statistics.median(generation_latencies),
                3,
            ),
            "generation_p95": _percentile(generation_latencies, 0.95),
            "pipeline_mean": round(
                statistics.mean(pipeline_latencies),
                3,
            ),
            "pipeline_p95": _percentile(pipeline_latencies, 0.95),
        },
        "tokens": {
            "input": sum(
                int(
                    row["observability"].get("usage", {}).get(
                        "input_tokens", 0
                    )
                )
                for row in rows
            ),
            "output": sum(
                int(
                    row["observability"].get("usage", {}).get(
                        "output_tokens", 0
                    )
                )
                for row in rows
            ),
        },
        "stages": stages,
        "wall_clock_ms": round(
            (time.perf_counter() - started) * 1000,
            3,
        ),
        "manual_review_required": True,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--legacy-source-root", type=Path, required=True)
    parser.add_argument("--legacy-source-commit", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument(
        "--table-facts",
        type=Path,
        default=DEFAULT_TABLE_FACTS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--model", default="qwen3-8b:ctx8192")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--evaluation-role",
        default="paired_adaptive_new_claim32_ab_not_generalization",
    )
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            run(build_parser().parse_args()),
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
