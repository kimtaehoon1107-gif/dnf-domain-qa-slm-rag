from __future__ import annotations

import unittest

from src.v3.diagnose_routing_bottleneck import (
    build_taxonomy_rows,
    classify_failure,
    summarize,
)


def _attribution(
    case_id: str,
    expected: str,
    *,
    groups: int,
    ordinal: int,
    actual: str = "retrieve",
) -> dict:
    return {
        "case_id": case_id,
        "query_ordinal": ordinal,
        "first_failure_stage": "ROUTING" if expected != actual else "PASS",
        "expected_route_action": expected,
        "actual_route_action": actual,
        "required_evidence_group_count": groups,
        "question_text_included": False,
        "gold_text_included": False,
    }


class RoutingBottleneckDiagnosticTest(unittest.TestCase):
    def test_exclusive_taxonomy_uses_parent_audit_for_decompose(self) -> None:
        decompose = _attribution("cross", "decompose", groups=2, ordinal=1)
        suspect = _attribution("same", "decompose", groups=2, ordinal=2)
        self.assertEqual(
            classify_failure(
                decompose,
                {"single_parent_coverable": False, "cross_parent": True},
            ),
            "DECOMPOSE_MISS",
        )
        self.assertEqual(
            classify_failure(
                suspect,
                {"single_parent_coverable": True, "cross_parent": False},
            ),
            "LABEL_SUSPECT",
        )
        self.assertEqual(
            classify_failure(
                _attribution("rt", "realtime_api", groups=0, ordinal=3),
                {"single_parent_coverable": False, "cross_parent": False},
            ),
            "REALTIME_MISS",
        )
        self.assertEqual(
            classify_failure(
                _attribution("reject", "reject", groups=0, ordinal=4),
                {"single_parent_coverable": False, "cross_parent": False},
            ),
            "REJECT_MISS",
        )

    def test_taxonomy_rows_use_frozen_requirement_count_only(self) -> None:
        attribution = [_attribution("same", "decompose", groups=3, ordinal=1)]
        parents = [
            {
                "case_id": "same",
                "dataset": "downgraded_canary_32",
                "single_parent_coverable": True,
                "cross_parent": False,
            }
        ]
        enumeration = [
            {
                "case_id": "same",
                "requirements": [{"id": 1}, {"id": 2}],
            }
        ]
        rows = build_taxonomy_rows(attribution, parents, enumeration)
        self.assertEqual(rows[0]["failure_type"], "LABEL_SUSPECT")
        self.assertTrue(rows[0]["planner_multi_field_signal"])
        self.assertFalse(rows[0]["question_text_included"])
        self.assertFalse(rows[0]["gold_text_included"])

    def test_parent_classification_must_be_exclusive(self) -> None:
        with self.assertRaises(RuntimeError):
            classify_failure(
                _attribution("bad", "decompose", groups=2, ordinal=1),
                {"single_parent_coverable": True, "cross_parent": True},
            )

    def test_frozen_summary_counts_and_planner_hypothesis(self) -> None:
        attributions = []
        taxonomy = []
        enumeration = []
        ordinal = 1
        specs = [
            *(
                ('LABEL_SUSPECT', 'decompose', groups, True)
                for groups in (2, 3, 4, 2, 3, 2, 2)
            ),
            ('DECOMPOSE_MISS', 'decompose', 2, True),
            ('DECOMPOSE_MISS', 'decompose', 3, False),
            *(('REJECT_MISS', 'reject', 0, False) for _ in range(3)),
            ('REALTIME_MISS', 'realtime_api', 0, False),
            ('REALTIME_MISS', 'realtime_api', 0, True),
        ]
        for failure_type, expected, groups, multi in specs:
            case_id = f"case-{ordinal}"
            attribution = _attribution(
                case_id, expected, groups=groups, ordinal=ordinal
            )
            attributions.append(attribution)
            taxonomy.append(
                {
                    "case_id": case_id,
                    "query_ordinal": ordinal,
                    "failure_type": failure_type,
                    "expected_route_action": expected,
                    "actual_route_action": "retrieve",
                    "required_evidence_group_count": groups,
                    "single_parent_coverable": failure_type == "LABEL_SUSPECT",
                    "cross_parent": failure_type == "DECOMPOSE_MISS",
                    "planner_requirement_count": 2 if multi else 1,
                    "planner_multi_field_signal": multi,
                    "tractability": "planner_path"
                    if failure_type in {"LABEL_SUSPECT", "DECOMPOSE_MISS"}
                    else "parked_answerability",
                }
            )
            enumeration.append(
                {
                    "case_id": case_id,
                    "requirements": [{}, {}] if multi else [{}],
                }
            )
            ordinal += 1
        for _ in range(18):
            case_id = f"case-{ordinal}"
            attributions.append(
                _attribution(
                    case_id,
                    "retrieve",
                    groups=1,
                    ordinal=ordinal,
                    actual="retrieve",
                )
            )
            enumeration.append({"case_id": case_id, "requirements": [{}]})
            ordinal += 1
        summary = summarize(
            attributions,
            taxonomy,
            enumeration,
            router_sha256="router",
            answerability_sha256="answerability",
        )
        self.assertEqual(summary["route_action_exact"]["successes"], 18)
        self.assertEqual(
            summary["failure_taxonomy"]["LABEL_SUSPECT"]["questions"][
                "successes"
            ],
            7,
        )
        self.assertEqual(
            summary["planner_hypothesis"]["genuine_decompose_miss_detected"][
                "successes"
            ],
            1,
        )
        self.assertEqual(
            summary["planner_hypothesis"][
                "parked_answerability_false_multi_signal"
            ]["successes"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
