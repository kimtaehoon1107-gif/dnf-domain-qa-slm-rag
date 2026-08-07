from __future__ import annotations

import argparse
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl


DIAGNOSTIC_VERSION = "product-free-rag-failure-attribution-r5-v1"
FAILURE_SLOTS = (1, 2, 4, 6, 7, 10, 11, 13, 14, 22, 26, 28, 32)
FROZEN_A6 = Path(
    "data/v3/evaluation/"
    "product_free_rag_a6_frozen_"
    "9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc.jsonl"
)
GOLD_RANK = Path(
    "reports/v3/product_free_rag_gold_chunk_rank_diagnostic_20260805.jsonl"
)
VALUE_PRESENCE = Path("reports/v3/product_value_presence_m3_20260805.jsonl")
ONE_SHOT = Path(
    "reports/v3/"
    "product_free_rag_a6_one_shot_"
    "4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl"
)
W6 = Path("reports/v3/product_free_rag_w6_relation_waterfall_v2_20260805.jsonl")
DEFAULT_OUTPUT = Path(
    "reports/v3/product_free_rag_failure_attribution_r5_20260806.jsonl"
)


# The first-failure stage is a human adjudication over frozen artifacts. The
# rationale is intentionally stored beside the decision so every row remains
# auditable without rerunning retrieval or generation.
ATTRIBUTIONS: dict[tuple[int, str], tuple[str, str]] = {
    (1, "transfer_limits"): (
        "S2",
        "M3 is partial: the pack has 1-day 200만원 and no-count-limit, but not 1회 50만원 or 1월 500만원.",
    ),
    (2, "maintenance_start"): (
        "S3",
        "The pack contains 8월 12일 15시, while Qwen exposed 14시 and never claimed 15시.",
    ),
    (2, "reopen_date"): (
        "S?",
        "This requirement did not fail: the pack and exposed claim both contain the 8월 13일 reopening date.",
    ),
    (4, "report_path"): (
        "S2",
        "M3 is none: the three-step path 캐릭터 이름 클릭 > 신고하기 > 거래 사기 등록 is absent from the pack.",
    ),
    (4, "privacy_request_penalty"): (
        "S?",
        "This requirement did not fail: 영구 게임 이용 제한 is present in the pack and exposed answer.",
    ),
    (6, "primal_will_shop_terms"): (
        "S?",
        "This supported requirement did not fail: 790개 and 계정당 1회 are present and exposed; the case-level issue was an unsupported requirement.",
    ),
    (7, "base_cooldown_change"): (
        "S2",
        "M3 is none: the overlapping pack sentence says only that cooldown decreases and omits both 20초 and 18초.",
    ),
    (7, "gale_option_cooldown_change"): (
        "S5",
        "The pack contains 12초→9초 and the approved claim exposes those values, but binds them to 타이드 바운드 instead of 질풍 개화.",
    ),
    (10, "daily_clear_requirement"): (
        "S4",
        "The pack contains 10회 and Qwen generated it, but the verifier rejected the claim as factual_values_not_in_evidence.",
    ),
    (10, "daily_fishing_limit"): (
        "S4",
        "The pack contains 계정당 1회 and 06시 and Qwen generated both, but the verifier rejected the claim as factual_values_not_in_evidence.",
    ),
    (11, "sales_period"): (
        "S3",
        "The pack contains the full 2026-06-04 through 2026-08-27 period, while Qwen omitted the 2026-08-27 end.",
    ),
    (11, "purchase_reset"): (
        "S?",
        "This requirement did not fail: 매주 목요일 06시 is present in the pack and exposed answer.",
    ),
    (11, "deletion_at"): (
        "S?",
        "This requirement did not fail: 2026-09-04 06시 is present in the pack and exposed answer.",
    ),
    (13, "mypin_properties"): (
        "S2",
        "M3 is partial: 13자리 and 3년 are present, but 연 5회 재발급 is absent before the later verifier rejection.",
    ),
    (14, "mobile_trading"): (
        "S?",
        "This requirement did not fail: the no-direct-trading answer is supported and exposed, although repeated.",
    ),
    (14, "available_views"): (
        "S3",
        "The pack contains both viewable information types, but Qwen produced no claim for either one.",
    ),
    (22, "bug_reporting_channel"): (
        "S1",
        "The 고객센터 gold chunk is absent from the final eight candidates; the measured hybrid rank is 28.",
    ),
    (26, "contract_price_duration"): (
        "S2",
        "M3 is partial: 30일 is present but 9,800 세라 is absent from the pack.",
    ),
    (26, "purchase_reward"): (
        "S?",
        "This requirement did not fail: 해방의 열쇠 10개 상자 1개 is present and exposed.",
    ),
    (28, "tropical_hat_box"): (
        "S4",
        "The pack and Qwen claim contain 계정당 5회, but the verifier rejected that claim as cross_parent_structured_value_conflict.",
    ),
    (32, "october_siv_fame"): (
        "S4",
        "The pack and raw claim contain +221, but the claim also bundles unsupported 구매 제한 1개 and the verifier removes the whole claim.",
    ),
}


STRICT_VALUE_KEYS = {
    (1, "transfer_limits"),
    (2, "maintenance_start"),
    (2, "reopen_date"),
    (6, "primal_will_shop_terms"),
    (7, "base_cooldown_change"),
    (7, "gale_option_cooldown_change"),
    (10, "daily_clear_requirement"),
    (10, "daily_fishing_limit"),
    (11, "sales_period"),
    (11, "purchase_reset"),
    (11, "deletion_at"),
    (13, "mypin_properties"),
    (26, "contract_price_duration"),
    (28, "tropical_hat_box"),
    (32, "october_siv_fame"),
}


UNSUPPORTED_INCIDENTS = (
    {
        "slot_ordinal": 6,
        "requirement_id": "primal_oath_exact_probability",
        "incident": "official 19/32 layer marked false-full; handled by the separate slot-6 re-adjudication commit",
    },
    {
        "slot_ordinal": 22,
        "requirement_id": "bug_report_response_deadline",
        "incident": "unsupported deadline was exposed as 12/4(목), a human-confirmed overclaim outside the 21 supported requirements",
    },
    {
        "slot_ordinal": 32,
        "requirement_id": "october_siv_account_limit",
        "incident": "unsupported account limit was bundled with supported +221 and caused whole-claim rejection",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _case_rows(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(row["slot_ordinal"]): row
        for row in rows
        if row.get("type") == "case"
    }


def _requirement(row: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    matches = [
        requirement
        for requirement in row["requirements"]
        if requirement["requirement_id"] == requirement_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one requirement {requirement_id}, found {len(matches)}"
        )
    return matches[0]


def _validate_stage_contract(row: dict[str, Any]) -> None:
    stage = row["attribution_stage"]
    final = row["gold_in_final_candidates"]
    presence = row["value_presence"]
    rejected = row["rejected_claims"]
    score = row["saved_requirement_score"]
    if stage == "S1" and final is not False:
        raise RuntimeError("S1 requires the gold chunk to be absent from final candidates")
    if stage == "S2" and (final is not True or presence not in {"value_present_partial", "value_present_none"}):
        raise RuntimeError("S2 requires final-candidate gold and partial/none value presence")
    if stage == "S3" and (presence != "value_present_full" or score["claim_complete"]):
        raise RuntimeError("S3 requires full pack value and incomplete saved claim")
    if stage == "S4" and (presence != "value_present_full" or not rejected):
        raise RuntimeError("S4 requires full pack value and at least one rejected claim")
    if stage == "S5" and (presence != "value_present_full" or not row["exposed_claims"]):
        raise RuntimeError("S5 requires full pack value and an exposed claim")
    if stage == "S?" and not score["claim_complete"]:
        raise RuntimeError("S? rows are retained successful requirements")


def build_rows(root: Path) -> list[dict[str, Any]]:
    paths = {
        "frozen_a6": root / FROZEN_A6,
        "gold_rank": root / GOLD_RANK,
        "value_presence": root / VALUE_PRESENCE,
        "one_shot": root / ONE_SHOT,
        "w6": root / W6,
    }
    frozen = {
        int(row["slot_ordinal"]): row for row in read_jsonl(paths["frozen_a6"])
    }
    ranks = _case_rows(read_jsonl(paths["gold_rank"]))
    presence = _case_rows(read_jsonl(paths["value_presence"]))
    one_shot = _case_rows(read_jsonl(paths["one_shot"]))
    w6 = _case_rows(read_jsonl(paths["w6"]))

    observed_keys = {
        (slot, str(requirement["requirement_id"]))
        for slot in FAILURE_SLOTS
        for requirement in frozen[slot]["requirements"]
        if requirement["expected_status"] == "supported"
    }
    if observed_keys != set(ATTRIBUTIONS):
        raise RuntimeError(
            "supported requirements in official failure slots changed: "
            f"missing={sorted(set(ATTRIBUTIONS) - observed_keys)}, "
            f"extra={sorted(observed_keys - set(ATTRIBUTIONS))}"
        )
    if len(observed_keys) != 21:
        raise RuntimeError(f"expected 21 supported requirements, found {len(observed_keys)}")

    output: list[dict[str, Any]] = []
    for slot, requirement_id in sorted(observed_keys):
        frozen_requirement = _requirement(frozen[slot], requirement_id)
        rank_requirement = _requirement(ranks[slot], requirement_id)
        presence_requirement = _requirement(presence[slot], requirement_id)
        score = next(
            score
            for score in one_shot[slot]["requirement_scores"]
            if score["requirement_id"] == requirement_id
        )
        old_w6 = None
        if slot in w6:
            matches = [
                requirement
                for requirement in w6[slot]["requirements"]
                if requirement["requirement_id"] == requirement_id
            ]
            old_w6 = matches[0]["drop_stage"] if matches else None
        stage, rationale = ATTRIBUTIONS[(slot, requirement_id)]
        row = {
            "type": "requirement_attribution",
            "diagnostic_version": DIAGNOSTIC_VERSION,
            "slot_ordinal": slot,
            "case_ref": f"A6-{slot}",
            "question": frozen[slot]["question_text"],
            "requirement_id": requirement_id,
            "required_values": list(frozen_requirement.get("required_values") or []),
            "value_type": frozen_requirement["value_type"],
            "value_group": (
                "numeric_date_time_currency"
                if (slot, requirement_id) in STRICT_VALUE_KEYS
                else "descriptive"
            ),
            "attribution_stage": stage,
            "attribution_rationale": rationale,
            "gold_in_final_candidates": bool(
                rank_requirement["in_final_candidates"]
            ),
            "hybrid_union_rank": rank_requirement["hybrid_union_rank"],
            "value_presence": presence_requirement["value_presence"],
            "assigned_pack_texts": [
                unit["text"] for unit in presence_requirement["assigned_units"]
            ],
            "exposed_claims": [
                claim["text"] for claim in one_shot[slot]["result"]["claims"]
            ],
            "rejected_claims": [
                {
                    "text": claim["text"],
                    "reasons": list(claim["reasons"]),
                }
                for claim in one_shot[slot]["result"]["rejected_claims"]
            ],
            "saved_requirement_score": {
                "value_complete": bool(score["value_complete"]),
                "claim_complete": bool(score["claim_complete"]),
            },
            "w6_v2_drop_stage": old_w6,
        }
        _validate_stage_contract(row)
        output.append(row)

    for incident in UNSUPPORTED_INCIDENTS:
        output.append(
            {
                "type": "unsupported_incident",
                "diagnostic_version": DIAGNOSTIC_VERSION,
                **incident,
            }
        )

    attributed = [row for row in output if row["type"] == "requirement_attribution"]
    stage_counts = Counter(row["attribution_stage"] for row in attributed)
    value_presence_by_group: dict[str, Counter[str]] = defaultdict(Counter)
    for row in attributed:
        value_presence_by_group[row["value_group"]][row["value_presence"]] += 1
    output.append(
        {
            "type": "summary",
            "diagnostic_version": DIAGNOSTIC_VERSION,
            "status": "diagnostic_complete_no_runtime_change",
            "official_human_accuracy_basis": "19/32",
            "official_failure_case_count": len(FAILURE_SLOTS),
            "supported_requirement_count": len(attributed),
            "actual_failed_supported_requirement_count": sum(
                row["attribution_stage"] != "S?" for row in attributed
            ),
            "retained_successful_requirement_count": stage_counts["S?"],
            "stage_counts": dict(sorted(stage_counts.items())),
            "value_presence_by_group": {
                group: dict(sorted(counts.items()))
                for group, counts in sorted(value_presence_by_group.items())
            },
            "unsupported_incident_count": len(UNSUPPORTED_INCIDENTS),
            "qwen_calls": 0,
            "runtime_modified": False,
            "input_sha256": {
                name: _sha256(path) for name, path in sorted(paths.items())
            },
        }
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-derive A6 first-failure attribution from frozen artifacts"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")
    rows = build_rows(root)
    write_jsonl(output, rows)
    summary = rows[-1]
    print(
        f"wrote {len(rows) - 1} records + summary to {output}; "
        f"stage_counts={summary['stage_counts']}; qwen_calls=0"
    )


if __name__ == "__main__":
    main()
