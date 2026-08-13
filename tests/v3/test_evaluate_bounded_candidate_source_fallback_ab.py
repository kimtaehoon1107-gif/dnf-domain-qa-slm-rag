from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_bounded_candidate_source_fallback_ab import (
    DEFAULT_CANARY_RUNTIME,
    DEFAULT_DEV_RUNTIME,
    DEFAULT_Q3_CASES,
    DEFAULT_SEGMENT_SCORES,
    _route_map,
    bounded_sources,
    build_bounded_fallback_inputs,
    build_q4_rows,
    enrich_assembler_cases,
    evaluate_and_freeze,
    summarize_q4,
)
from src.v3.evaluate_extractive_assembler_v3_chunk_diverse import (
    assemble_chunk_diverse_configuration,
)
from src.v3.evaluate_requirement_retrieval_ab import (
    ASSEMBLER_K,
    ASSEMBLER_THRESHOLD,
    DEFAULT_ASSEMBLER_CASES,
)
from src.v3.evaluate_router_backbone_mixed_metrics import (
    DEFAULT_CANARY,
    DEFAULT_CHUNKS,
    DEFAULT_DEV,
    DEFAULT_ENUMERATION,
    DEFAULT_GROUND_TRUTH,
)

ROOT = Path(__file__).resolve().parents[2]


def _actual_rows():
    assembler = enrich_assembler_cases(
        read_jsonl(ROOT / DEFAULT_ASSEMBLER_CASES),
        read_jsonl(ROOT / DEFAULT_ENUMERATION),
    )
    chunks = read_jsonl(ROOT / DEFAULT_CHUNKS)
    routes = _route_map(
        read_jsonl(ROOT / DEFAULT_DEV_RUNTIME), read_jsonl(ROOT / DEFAULT_CANARY_RUNTIME)
    )
    cases, scores = build_bounded_fallback_inputs(
        assembler_cases=assembler,
        segment_score_rows=read_jsonl(ROOT / DEFAULT_SEGMENT_SCORES),
        routes=routes,
        chunks=chunks,
    )
    assembled = assemble_chunk_diverse_configuration(
        cases, scores, threshold=ASSEMBLER_THRESHOLD, k=ASSEMBLER_K
    )
    rows = build_q4_rows(
        ground_truth_rows=read_jsonl(ROOT / DEFAULT_GROUND_TRUTH),
        evaluation_rows=read_jsonl(ROOT / DEFAULT_DEV) + read_jsonl(ROOT / DEFAULT_CANARY),
        q3_rows=read_jsonl(ROOT / DEFAULT_Q3_CASES),
        assembler_cases=assembler,
        fallback_assembler_rows=assembled,
        routes=routes,
        chunks=chunks,
    )
    return rows


def test_bounded_sources_use_only_existing_route_signal_top_two():
    route = {
        "source_ids": ["dnf_seria_shop"],
        "routing_signals": {
            "candidate_sources": ["dnf_seria_shop", "dnf_event", "dnf_notice"]
        },
    }
    assert bounded_sources(route) == ["dnf_seria_shop", "dnf_event"]


def test_q4_recovers_remaining_mixed_case_without_frozen_regression():
    rows = _actual_rows()
    result = summarize_q4(rows)

    assert result["arm_q3_mixed"]["correct_mixed_partial_span_strict"]["successes"] == 12
    assert result["arm_q4_mixed"]["correct_mixed_partial_span_strict"]["successes"] == 13
    assert result["arm_q4_mixed"]["mixed_overclaim"]["successes"] == 0
    assert result["docs_only"]["grounded"]["successes"] >= 61
    assert result["docs_only"]["grounded_regression_case_ids"] == []
    assert result["docs_only"]["new_false_full_case_ids"] == []
    assert result["temporal_violation_chunk_ids"] == []
    assert result["strict_gate_passed"] is True
    assert result["decision"] == "DEVELOPMENT_GO_NEW_AUTHORED_VALIDATION"


def test_mileage_case_expands_only_to_event_and_shop_and_uses_no_gold_decision():
    rows = _actual_rows()
    case_id = (
        "authored_canary_sha256_"
        "9e2c7f69dd204fd5229a8e21b441b7d2c07b3e4ba5eb73ee5b40f5867f4bb875"
    )
    row = next(item for item in rows if item["case_id"] == case_id)

    assert row["answerability_signal"]["label"] == "partial"
    assert row["fallback_triggered"] is True
    assert row["fallback_committed"] is True
    assert set(row["bounded_source_ids"]) == {"dnf_seria_shop", "dnf_event"}
    assert row["q4_mixed_metrics"]["correct_mixed_partial_span_strict"] is True
    assert row["gold_ids_available_to_trigger_or_commit"] is False


def test_freeze_is_content_addressed_and_reproducible(tmp_path: Path):
    first = evaluate_and_freeze(ROOT, artifact_root=tmp_path)
    second = evaluate_and_freeze(ROOT, artifact_root=tmp_path)

    assert first["cases_sha256"] == second["cases_sha256"]
    assert first["report_json_sha256"] == second["report_json_sha256"]
    assert first["report_md_sha256"] == second["report_md_sha256"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
