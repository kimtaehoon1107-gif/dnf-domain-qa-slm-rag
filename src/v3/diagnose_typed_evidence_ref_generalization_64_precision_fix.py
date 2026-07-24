from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_grounded_llm_replay import run_fixed_requirement_replay
from src.v3.score_typed_evidence_ref_generalization import (
    NORMALIZATION_CONTRACT,
    SCORER_VERSION,
    score_generalization_cases,
)


DEFAULT_SEALED = Path(
    "data/v3/evaluation/"
    "typed_evidence_ref_generalization_64_sealed_"
    "e56780c88fcf74d339833d3bc31d125a46d6144839eb10e513d2edf32b85a597.jsonl"
)
DEFAULT_SOURCE = Path(
    "outputs/v3/typed_evidence_ref_generalization_64_one_shot_"
    "e56780c88fcf74d3/"
    "typed_evidence_ref_generalization_64_cases_"
    "9ae8e0443e0948457ef53e98493f81ee2909159716d20b247f85dc20429d2efb.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_TEMPORAL = Path(
    "data/v3/temporal/"
    "global_temporal_overlay_v3.2_"
    "f6e359dffae092f30e9129f76460bde17f01fd81165a063583095ea43a1fa317.jsonl"
)
DEFAULT_TABLE_FACTS = Path(
    "data/v3/structured/"
    "table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_OUTPUT = Path(
    "outputs/v3/diagnostics/"
    "typed_evidence_ref_generalization_64_precision_fix_verifier_only.jsonl"
)
DEFAULT_SUMMARY = Path(
    "reports/v3/"
    "typed_evidence_ref_generalization_64_precision_fix_diagnostic.json"
)


class RecordedGenerationError(RuntimeError):
    pass


def _compatible_reviewed(row: dict[str, Any]) -> dict[str, Any]:
    evidence_groups = []
    for index, requirement in enumerate(row["requirements"], 1):
        units = requirement["acceptable_evidence_units"]
        evidence_groups.append(
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
        "evidence_groups": evidence_groups,
        "expected_requirement_count": len(row["requirements"]),
    }


def _recorded_generator(calls: list[dict[str, Any]]):
    call_index = 0

    def generate(**_: Any) -> dict[str, Any]:
        nonlocal call_index
        if call_index >= len(calls):
            raise RuntimeError("recorded generation calls exhausted")
        call = copy.deepcopy(calls[call_index])
        call_index += 1
        if "output" not in call:
            raise RecordedGenerationError(
                str(call.get("error") or "recorded call has no output")
            )
        return call

    def assert_consumed() -> None:
        if call_index != len(calls):
            raise RuntimeError(
                f"unused recorded generation calls: {len(calls) - call_index}"
            )

    return generate, assert_consumed


def _baseline_row(
    sealed: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id": sealed["candidate_id"],
        "arm0": {
            "candidate_chunk_ids": list(source["candidate_chunk_ids"]),
        },
        "arm0_score": {
            "all_groups_hit": False,
            "all_evidence_spans_hit": False,
            "relevant_citation_count": 0,
            "citation_count": 0,
        },
    }


def _candidate_pool_row(
    sealed: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    pools = source["requirement_candidate_chunk_ids"]
    if len(pools) != len(sealed["requirements"]):
        raise RuntimeError(
            f"requirement pool count differs for slot {sealed['slot_ordinal']}"
        )
    return {
        "candidate_id": sealed["candidate_id"],
        "slot_ordinal": sealed["slot_ordinal"],
        "question_text": sealed["question_text"],
        "requirement_candidate_pools": [
            {
                "requirement_id": requirement["requirement_id"],
                "query": requirement["relation"],
                "subject_arm_full": {
                    "candidate_chunk_ids": list(pools[index]),
                },
            }
            for index, requirement in enumerate(sealed["requirements"])
        ],
    }


def _requirement_changes(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[dict[str, Any]]:
    before_decisions = {
        row["requirement_id"]: row
        for row in before["verified_output"]["requirements"]
    }
    after_decisions = {
        row["requirement_id"]: row
        for row in after["verified_output"]["requirements"]
    }
    before_audits = {
        row["requirement_id"]: row
        for row in before["verified_output"]["verification"]["requirements"]
    }
    after_audits = {
        row["requirement_id"]: row
        for row in after["verified_output"]["verification"]["requirements"]
    }
    changes = []
    for requirement_id in before_decisions:
        before_decision = before_decisions[requirement_id]
        after_decision = after_decisions[requirement_id]
        before_audit = before_audits[requirement_id]
        after_audit = after_audits[requirement_id]
        compared = {
            "status": (
                before_decision.get("status"),
                after_decision.get("status"),
            ),
            "answer": (
                before_decision.get("answer"),
                after_decision.get("answer"),
            ),
            "failure_reasons": (
                before_audit.get("failure_reasons", []),
                after_audit.get("failure_reasons", []),
            ),
            "normalized_value": (
                before_audit.get("normalized_value"),
                after_audit.get("normalized_value"),
            ),
        }
        if any(old != new for old, new in compared.values()):
            changes.append(
                {
                    "requirement_id": requirement_id,
                    **{
                        key: {"before": old, "after": new}
                        for key, (old, new) in compared.items()
                    },
                }
            )
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Replay stored generalization-64 model calls through the current "
            "verifier for post-hoc diagnosis only."
        )
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--table-facts", type=Path, default=DEFAULT_TABLE_FACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    output_path = resolved(args.output)
    summary_path = resolved(args.summary)
    if output_path.exists() or summary_path.exists():
        raise RuntimeError("diagnostic output or summary already exists")

    sealed_rows = read_jsonl(resolved(args.sealed))
    source_rows = read_jsonl(resolved(args.source))
    if len(sealed_rows) != 64 or len(source_rows) != 64:
        raise RuntimeError("diagnostic requires exactly 64 sealed and source rows")
    source_by_id = {row["candidate_id"]: row for row in source_rows}
    if {row["candidate_id"] for row in sealed_rows} != set(source_by_id):
        raise RuntimeError("sealed and source candidate IDs differ")

    ordered_sources = [
        source_by_id[sealed["candidate_id"]] for sealed in sealed_rows
    ]
    recorded_calls = [
        call
        for source in ordered_sources
        for call in source["model_call"]["calls"]
    ]
    generator, assert_consumed = _recorded_generator(recorded_calls)
    reviewed_rows = [_compatible_reviewed(row) for row in sealed_rows]
    baseline_rows = [
        _baseline_row(sealed, source)
        for sealed, source in zip(
            sealed_rows,
            ordered_sources,
            strict=True,
        )
    ]
    pool_rows = [
        _candidate_pool_row(sealed, source)
        for sealed, source in zip(
            sealed_rows,
            ordered_sources,
            strict=True,
        )
    ]

    chunks = read_jsonl(resolved(args.chunks))
    generated_rows = run_fixed_requirement_replay(
        reviewed_rows=reviewed_rows,
        baseline_rows=baseline_rows,
        chunks=chunks,
        documents=read_jsonl(resolved(args.documents)),
        temporal_rows=read_jsonl(resolved(args.temporal)),
        table_facts=read_jsonl(resolved(args.table_facts)),
        model="qwen3-8b:ctx8192",
        as_of="2026-07-22",
        reasoning_effort="high",
        timeout_seconds=180,
        batch_generator=generator,
        typed_batch_generator=generator,
        split_evidence_schema=True,
        batch_requirements=True,
        typed_evidence_refs=True,
        candidate_pool_rows=pool_rows,
        candidate_pool_arm="subject_arm_full",
    )
    assert_consumed()

    replay_rows = []
    for generated, source in zip(
        generated_rows,
        ordered_sources,
        strict=True,
    ):
        if (
            generated["candidate_chunk_ids"]
            != source["candidate_chunk_ids"]
            or generated["requirement_candidate_chunk_ids"]
            != source["requirement_candidate_chunk_ids"]
        ):
            raise RuntimeError(
                f"candidate replay mismatch: {generated['candidate_id']}"
            )
        if any(
            "output" not in call
            for call in source["model_call"]["calls"]
        ):
            generated["verified_output"] = copy.deepcopy(
                source["verified_output"]
            )
        replay_rows.append(
            {
                **generated,
                "model_call": source["model_call"],
                "slot_ordinal": source["slot_ordinal"],
                "source_id": source["source_id"],
                "primary_dimension": source["primary_dimension"],
                "retrieval": source["retrieval"],
            }
        )

    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    scored_rows, score_summary = score_generalization_cases(
        sealed_rows,
        replay_rows,
        chunks_by_id=chunks_by_id,
    )
    changes = []
    for before, after in zip(
        ordered_sources,
        scored_rows,
        strict=True,
    ):
        requirement_changes = _requirement_changes(before, after)
        old_score = before["holdout_score"]
        new_score = after["holdout_score"]
        score_changed = any(
            old_score.get(key) != new_score.get(key)
            for key in (
                "outcome",
                "gold_value_complete",
                "false_full",
                "failure_stage",
            )
        )
        if requirement_changes or score_changed:
            changes.append(
                {
                    "slot_ordinal": after["slot_ordinal"],
                    "candidate_id": after["candidate_id"],
                    "question_text": after["question_text"],
                    "before": {
                        key: old_score.get(key)
                        for key in (
                            "outcome",
                            "gold_value_complete",
                            "false_full",
                            "failure_stage",
                        )
                    },
                    "after": {
                        key: new_score.get(key)
                        for key in (
                            "outcome",
                            "gold_value_complete",
                            "false_full",
                            "failure_stage",
                        )
                    },
                    "requirements": requirement_changes,
                }
            )

    old_correct = sum(
        row["holdout_score"]["gold_value_complete"] for row in ordered_sources
    )
    new_correct = score_summary["gold_value_complete"]["successes"]
    recovered_slots = [
        row["slot_ordinal"]
        for row in changes
        if not row["before"]["gold_value_complete"]
        and row["after"]["gold_value_complete"]
    ]
    regressed_slots = [
        row["slot_ordinal"]
        for row in changes
        if row["before"]["gold_value_complete"]
        and not row["after"]["gold_value_complete"]
    ]
    summary = {
        "evaluation_role": (
            "post_hoc_diagnostic_only_not_a_generalization_score"
        ),
        "headline_replacement_allowed": False,
        "sealed_result_preserved": {
            "gold_value_complete": {"successes": old_correct, "total": 64},
            "source_path": args.source.as_posix(),
            "source_sha256": file_sha256(resolved(args.source)),
        },
        "diagnostic_replay": {
            "new_model_calls": 0,
            "retrieval_reexecuted": False,
            "stored_candidates_reused": True,
            "stored_model_outputs_reused": True,
            "scorer_version": SCORER_VERSION,
            "normalization_contract": NORMALIZATION_CONTRACT,
            "gold_value_complete": {
                "successes": new_correct,
                "total": 64,
            },
            "score_delta": new_correct - old_correct,
            "recovered_slots": recovered_slots,
            "regressed_slots": regressed_slots,
            "changed_slot_count": len(changes),
            "score_summary": score_summary,
        },
        "changes": changes,
        "inputs": {
            "sealed": {
                "path": args.sealed.as_posix(),
                "sha256": file_sha256(resolved(args.sealed)),
            },
            "chunks": {
                "path": args.chunks.as_posix(),
                "sha256": file_sha256(resolved(args.chunks)),
            },
            "documents": {
                "path": args.documents.as_posix(),
                "sha256": file_sha256(resolved(args.documents)),
            },
            "temporal": {
                "path": args.temporal.as_posix(),
                "sha256": file_sha256(resolved(args.temporal)),
            },
            "table_facts": {
                "path": args.table_facts.as_posix(),
                "sha256": file_sha256(resolved(args.table_facts)),
            },
        },
        "output": args.output.as_posix(),
    }

    write_jsonl(output_path, scored_rows)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "evaluation_role": summary["evaluation_role"],
                "sealed_score": f"{old_correct}/64",
                "diagnostic_score": f"{new_correct}/64",
                "score_delta": new_correct - old_correct,
                "recovered_slots": recovered_slots,
                "regressed_slots": regressed_slots,
                "changed_slot_count": len(changes),
                "new_model_calls": 0,
                "retrieval_reexecuted": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
