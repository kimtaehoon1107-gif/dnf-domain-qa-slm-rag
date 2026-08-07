from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl
from src.v3 import product_minimal_verifier as verifier


DEFAULT_INPUTS = (
    (
        "a5_adaptive",
        Path(
            "reports/v3/"
            "product_free_rag_a5_current_product_adaptive_replay_20260804.jsonl"
        ),
    ),
    (
        "existing32",
        Path(
            "reports/v3/"
            "product_free_rag_existing32_step1_clause_numeric_20260804.jsonl"
        ),
    ),
    (
        "new_claim32",
        Path(
            "reports/v3/"
            "product_free_rag_new_claim32_step1_clause_numeric_20260804.jsonl"
        ),
    ),
)
DEFAULT_SUPPLEMENTS = (
    (
        "new_claim32_slot3_saved_raw_supplement",
        Path(
            "reports/v3/"
            "product_free_rag_new_claim32_adaptive_20260803.jsonl"
        ),
        3,
    ),
)
DEFAULT_OUTPUT = Path(
    "reports/v3/"
    "product_minimal_verifier_step1_saved_output_replay_20260804.jsonl"
)


def legacy_required_factual_value_present(
    question: str,
    claim_text: str,
) -> bool:
    if verifier._NUMERIC_QUESTION.search(question) is None:
        return True
    return bool(
        verifier._numeric_values(claim_text)
        or verifier._CLOCK_COLON.search(claim_text)
        or verifier._CLOCK_KOREAN.search(claim_text)
        or verifier._KOREAN_QUANTIFIED_VALUE.search(claim_text)
    )


def stored_claims(result: dict[str, Any]) -> list[dict[str, Any]]:
    claims = [
        {
            "source": "accepted",
            "claim_index": None,
            "text": str(claim.get("text") or ""),
            "evidence_refs": list(claim.get("evidence_refs") or []),
            "reasons": [],
        }
        for claim in result.get("claims") or []
        if str(claim.get("text") or "").strip()
    ]
    claims.extend(
        {
            "source": "rejected",
            "claim_index": rejected.get("claim_index"),
            "text": str(rejected.get("text") or ""),
            "evidence_refs": list(rejected.get("evidence_refs") or []),
            "reasons": list(rejected.get("reasons") or []),
        }
        for rejected in result.get("rejected_claims") or []
        if str(rejected.get("text") or "").strip()
    )
    return claims


def replay_case_claims(
    dataset: str,
    case: dict[str, Any],
) -> list[dict[str, Any]]:
    question = str(case.get("question") or "")
    rows = []
    for claim in stored_claims(case.get("result") or {}):
        old_allowed = legacy_required_factual_value_present(
            question,
            claim["text"],
        )
        new_allowed = verifier._required_factual_value_present(
            question,
            claim["text"],
        )
        rows.append(
            {
                "type": "claim",
                "dataset": dataset,
                "slot_ordinal": case.get("slot_ordinal"),
                "question": question,
                "case_false_full": bool(case.get("false_full_candidate")),
                **claim,
                "old_numeric_gate_allowed": old_allowed,
                "new_numeric_gate_allowed": new_allowed,
                "numeric_gate_changed": old_allowed != new_allowed,
            }
        )
    return rows


def replay_reports(
    inputs: tuple[tuple[str, Path], ...],
    supplements: tuple[tuple[str, Path, int], ...] = (),
) -> list[dict[str, Any]]:
    rows = []
    unavailable_cases = []
    for dataset, path in inputs:
        for case in read_jsonl(path):
            if case.get("type") != "case":
                continue
            result = case.get("result") or {}
            empty_rejections = [
                rejection
                for rejection in result.get("rejected_claims") or []
                if not str(rejection.get("text") or "").strip()
            ]
            if empty_rejections:
                unavailable_cases.append(
                    {
                        "dataset": dataset,
                        "slot_ordinal": case.get("slot_ordinal"),
                        "reason": "post_verifier_claim_text_not_preserved",
                    }
                )
            rows.extend(replay_case_claims(dataset, case))

    supplemented_cases = []
    for dataset, path, slot_ordinal in supplements:
        matching_cases = [
            case
            for case in read_jsonl(path)
            if case.get("type") == "case"
            and int(case.get("slot_ordinal") or 0) == slot_ordinal
        ]
        if len(matching_cases) != 1:
            raise RuntimeError(
                f"expected one supplemental slot {slot_ordinal} in {path}"
            )
        case = matching_cases[0]
        claims = stored_claims(case.get("result") or {})
        if not claims:
            raise RuntimeError(
                f"supplemental slot {slot_ordinal} has no stored claim text"
            )
        supplemented_cases.append(
            {
                "dataset": "new_claim32",
                "slot_ordinal": slot_ordinal,
                "source": str(path),
            }
        )
        rows.extend(replay_case_claims(dataset, case))

    loosened = [
        row
        for row in rows
        if not row["old_numeric_gate_allowed"]
        and row["new_numeric_gate_allowed"]
    ]
    tightened = [
        row
        for row in rows
        if row["old_numeric_gate_allowed"]
        and not row["new_numeric_gate_allowed"]
    ]
    new_false_full = [
        row
        for row in loosened
        if row["case_false_full"]
    ]
    unchanged_false_full = [
        row
        for row in rows
        if row["case_false_full"]
        and row["old_numeric_gate_allowed"]
        and row["new_numeric_gate_allowed"]
    ]
    summary = {
        "type": "summary",
        "measurement": "same_saved_claim_old_vs_new_pure_numeric_gate",
        "qwen_calls": 0,
        "retrieval_calls": 0,
        "claim_count": len(rows),
        "raw_unavailable_cases": unavailable_cases,
        "supplemented_cases": supplemented_cases,
        "effective_unavailable_cases": [
            row
            for row in unavailable_cases
            if not any(
                supplement["dataset"] == row["dataset"]
                and supplement["slot_ordinal"] == row["slot_ordinal"]
                for supplement in supplemented_cases
            )
        ],
        "changed_claim_count": len(loosened) + len(tightened),
        "loosened_claims": [
            {
                "dataset": row["dataset"],
                "slot_ordinal": row["slot_ordinal"],
                "text": row["text"],
            }
            for row in loosened
        ],
        "tightened_claims": [
            {
                "dataset": row["dataset"],
                "slot_ordinal": row["slot_ordinal"],
                "text": row["text"],
            }
            for row in tightened
        ],
        "new_false_full_claims": [
            {
                "dataset": row["dataset"],
                "slot_ordinal": row["slot_ordinal"],
                "text": row["text"],
            }
            for row in new_false_full
        ],
        "unchanged_false_full_slots": sorted(
            {
                (row["dataset"], int(row["slot_ordinal"]))
                for row in unchanged_false_full
            }
        ),
    }
    return [*rows, summary]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay the STEP 1 numeric gate on identical saved claims."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    rows = replay_reports(DEFAULT_INPUTS, DEFAULT_SUPPLEMENTS)
    write_jsonl(args.output, rows)
    print(json.dumps(rows[-1], ensure_ascii=False))


if __name__ == "__main__":
    main()
