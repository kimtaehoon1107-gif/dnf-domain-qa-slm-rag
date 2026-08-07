from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.v3.evaluate_requirement_surface_query_canary import (
    CONTROL_STRATA,
    DECISION_INPUT_FIELDS,
    EXPECTED_SOURCES,
    POSITIVE_STRATA,
    collect_pair_outputs,
    create_run_authorization,
    evaluate_pair_outputs,
    summarize_cases,
    validate_reviewed_export,
)


STRATA = (
    "positive_coordination_a",
    "positive_coordination_b",
    "single_requirement_control",
    "three_requirement_control",
)


def _fixture() -> tuple[list[dict], dict[str, dict], list[dict]]:
    rows = []
    chunks = {}
    pairs = []
    ordinal = 0
    for source_id in EXPECTED_SOURCES:
        for stratum in STRATA:
            ordinal += 1
            requirement_count = (
                2
                if stratum in POSITIVE_STRATA
                else 1
                if stratum == "single_requirement_control"
                else 3
            )
            requirements = []
            groups = []
            arm1_decisions = []
            for requirement_index in range(1, requirement_count + 1):
                chunk_id = f"chunk_{ordinal}_{requirement_index}"
                span = f"정답 {ordinal}-{requirement_index}"
                chunks[chunk_id] = {
                    "chunk_id": chunk_id,
                    "display_text": span,
                }
                requirement_id = f"requirement_{requirement_index}"
                requirements.append(
                    {
                        "requirement_id": requirement_id,
                        "subject": f"대상 {ordinal}",
                        "relation": f"속성 {requirement_index}",
                        "value_type": "text",
                        "subject_group": f"대상 {ordinal}",
                    }
                )
                groups.append(
                    {
                        "group_id": f"evidence_{requirement_index}",
                        "requirement_id": requirement_id,
                        "acceptable_chunk_ids": [chunk_id],
                        "evidence_span": span,
                    }
                )
                arm1_decisions.append(
                    {
                        "requirement_id": requirement_id,
                        "status": "supported_exact",
                        "citations": [
                            {
                                "chunk_id": chunk_id,
                                "start_char": 0,
                                "end_char": len(span),
                                "text": span,
                            }
                        ],
                    }
                )
            arm0_decisions = copy.deepcopy(arm1_decisions)
            if stratum in POSITIVE_STRATA:
                arm0_decisions[-1] = {
                    "requirement_id": requirements[-1]["requirement_id"],
                    "status": "unsupported",
                    "citations": [],
                }
            candidate_id = f"candidate_{ordinal}"
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "slot_ordinal": ordinal,
                    "source_id": source_id,
                    "stratum": stratum,
                    "question_text": f"질문 {ordinal}",
                    "expected_surface_query_action": (
                        "apply" if stratum in POSITIVE_STRATA else "bypass"
                    ),
                    "requirements": requirements,
                    "evidence_groups": groups,
                    "human_review_decision": "approve",
                    "human_reviewer_id": "human",
                    "human_reviewed_at": "2026-07-22T00:00:00+09:00",
                    "review_status": "user_full_review_approved",
                    "sealed_scoring_allowed": False,
                    "final_benchmark_eligible": False,
                    "independent_holdout_claim_allowed": False,
                    "training_allowed": False,
                }
            )
            candidate_ids = [
                group["acceptable_chunk_ids"][0] for group in groups
            ]
            pairs.append(
                {
                    "candidate_id": candidate_id,
                    "surface_query_applied": stratum in POSITIVE_STRATA,
                    "surface_query_audit": (
                        {"kind": "fixture"} if stratum in POSITIVE_STRATA else None
                    ),
                    "arm0": {
                        "decisions": arm0_decisions,
                        "candidate_chunk_ids": candidate_ids,
                        "temporal_violation_chunk_ids": [],
                    },
                    "arm1": {
                        "decisions": copy.deepcopy(arm1_decisions),
                        "candidate_chunk_ids": candidate_ids,
                        "temporal_violation_chunk_ids": [],
                    },
                    "gold_available_to_decision": False,
                    "decision_input_fields": list(DECISION_INPUT_FIELDS),
                }
            )
    return rows, chunks, pairs


def _review_manifest() -> dict:
    return {
        "reviewed_export": {"sha256": "reviewed-sha", "row_count": 32},
        "review": {
            "progress": {"approved": 32, "rejected": 0, "pending": 0}
        },
        "execution": {
            "sealed_run_count_allowed": 0,
            "sealed_scoring_allowed": False,
        },
    }


def test_fixture_positive_apply_bypass_invariance_and_all_gates() -> None:
    assert set(EXPECTED_SOURCES) == {
        "dnf_notice",
        "dnf_update",
        "dnf_event",
        "dnf_game_guide",
        "dnf_faq",
        "dnf_account_policy",
        "dnf_seria_shop",
        "dnf_monthly_item",
    }
    rows, chunks, pairs = _fixture()
    evaluated = evaluate_pair_outputs(rows, pairs, chunks_by_id=chunks)
    result = summarize_cases(evaluated)

    assert result["decision"] == "DEVELOPMENT_CANARY_GO"
    assert all(result["preregistered_gate_checks"].values())
    assert result["metrics"]["positive_application"] == {
        "successes": 16,
        "total": 16,
        "rate": 1.0,
    }
    assert result["metrics"]["control_bypass"]["successes"] == 16
    assert result["metrics"]["bypass_output_mutation_case_ids"] == []
    assert len(result["metrics"]["strict_improvement_case_ids"]) == 16


def test_bypass_mutation_fails_preregistered_gate() -> None:
    rows, chunks, pairs = _fixture()
    control = next(
        row for row in pairs if row["surface_query_applied"] is False
    )
    control["arm1"]["decisions"][0]["status"] = "unsupported"
    control["arm1"]["decisions"][0]["citations"] = []

    result = summarize_cases(
        evaluate_pair_outputs(rows, pairs, chunks_by_id=chunks)
    )

    assert result["decision"] == "DEVELOPMENT_NO_GO"
    assert result["preregistered_gate_checks"]["bypass_output_mutation_zero"] is False


def test_reviewed_export_does_not_itself_authorize_scoring() -> None:
    rows, _, _ = _fixture()
    validate_reviewed_export(rows, _review_manifest(), reviewed_sha256="reviewed-sha")

    manifest = _review_manifest()
    manifest["execution"]["sealed_run_count_allowed"] = 1
    with pytest.raises(RuntimeError, match="alone must not authorize"):
        validate_reviewed_export(rows, manifest, reviewed_sha256="reviewed-sha")


def test_gold_is_not_passed_to_pair_runner() -> None:
    rows, _, pairs = _fixture()

    class RecordingRunner:
        def __init__(self) -> None:
            self.seen = []
            self.by_id = {row["candidate_id"]: row for row in pairs}

        def run_pair(self, decision_input: dict[str, str]) -> dict:
            self.seen.append(decision_input)
            return self.by_id[decision_input["candidate_id"]]

    runner = RecordingRunner()
    outputs = collect_pair_outputs(rows, runner)

    assert len(outputs) == 32
    assert all(set(row) == set(DECISION_INPUT_FIELDS) for row in runner.seen)
    assert all("requirements" not in row and "evidence_groups" not in row for row in runner.seen)


def test_evaluator_has_no_case_specific_target_literals() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src/v3/evaluate_requirement_surface_query_canary.py"
    ).read_text(encoding="utf-8")
    assert "TARGET_LITERAL_SPANS" not in source
    assert "광휘의 행로" not in source
    assert "최후의 조율자" not in source


def test_authorization_freezes_packet_model_index_and_planner_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows, _, _ = _fixture()
    reviewed_path = tmp_path / "reviewed.jsonl"
    reviewed_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    import src.v3.evaluate_requirement_surface_query_canary as evaluator

    reviewed_sha = evaluator.file_sha256(reviewed_path)
    manifest = _review_manifest()
    manifest["reviewed_export"]["sha256"] = reviewed_sha
    manifest_path = tmp_path / "reviewed_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    provenance = {
        "files": {
            "evaluator_source": {"sha256": "eval-sha"},
            "bm25_index": {"sha256": "bm25-sha"},
            "dense_embeddings": {"sha256": "dense-sha"},
        },
        "planner": {
            "tag": "qwen3:8b",
            "identity_scope": "ollama_tag_only_not_binary_digest",
            "temperature": 0,
        },
        "reranker": {"model": "bge", "revision": "rev", "max_length": 512},
        "source_commit": "commit",
    }
    monkeypatch.setattr(evaluator, "_runtime_provenance", lambda root, model: provenance)

    result = create_run_authorization(
        root=tmp_path,
        reviewed_path=reviewed_path,
        reviewed_manifest_path=manifest_path,
        approved_by="human",
        planner_model="qwen3:8b",
    )

    authorization = result["authorization"]
    assert authorization["reviewed_packet"]["sha256"] == reviewed_sha
    assert authorization["runtime_provenance"] == provenance
    assert authorization["allowed_run_count"] == 1
    assert authorization["constraints"]["automatic_runtime_or_canonical_promotion"] is False
    assert Path(result["path"]).exists()
