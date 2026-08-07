from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.evaluate_evidence_adjudication import evaluate_adjudication


class EvidenceAdjudicationMetricTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    CASES = ROOT / (
        "data/v3/evidence/claim_reranker_cases_"
        "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a.jsonl"
    )
    REPORT = ROOT / (
        "reports/v3/claim_reranker_runtime_"
        "f37db5f17f3d20553d14922471c5bf7415ff942b12746dfad6d831a6a0ef1df9.json"
    )

    def test_original_and_adjudicated_metrics_remain_separate(self) -> None:
        report = json.loads(self.REPORT.read_text(encoding="utf-8"))
        cases = read_jsonl(self.CASES)
        decisions = {
            "비인가 프로그램 사용 주의사항은 뭐야?": "confirm_search_failure",
            "서약 / 결정 사용 방법은 뭐야?": "accept_alternative",
            "세라샵 아이템 청약철회는 구입 후 며칠 안에 문의해야 하고, 언제 불가능해?": "reject_alternative",
        }
        overlays = []
        for mismatch in report["strict_mismatches"]:
            case = next(row for row in cases if row["case_id"] == mismatch["case_id"])
            decision = decisions[mismatch["question"]]
            overlays.append(
                {
                    "case_id": mismatch["case_id"],
                    "evidence_group_id": mismatch["missing_group_ids"][0],
                    "candidate_chunk_id": case["response"]["citation_chunk_ids"][0],
                    "decision": decision,
                    "approved": decision == "accept_alternative",
                    "acceptable_sibling_addition": decision == "accept_alternative",
                    "search_failure_confirmed": decision == "confirm_search_failure",
                    "alternative_evidence_span": "사람이 확인한 후보 근거"
                    if decision == "accept_alternative"
                    else None,
                    "reviewer_type": "human",
                    "training_allowed": False,
                    "final_benchmark_eligible": False,
                }
            )

        result = evaluate_adjudication(report, cases, overlays)

        self.assertEqual(result["original_strict_citation"]["hits"], 56)
        self.assertEqual(result["adjudicated_semantic_citation"]["hits"], 57)
        self.assertEqual(result["gold_replacement_count"], 0)
        self.assertEqual(result["search_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
