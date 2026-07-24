import copy
import unittest

from src.v3.requirement_surface_query import (
    build_surface_scoring_requirements,
    extract_entity_coordinated_surfaces,
)
from src.v3.requirement_entity_anchor import anchor_requirements, build_official_entity_index


class RequirementSurfaceQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        anchor = {"phrase": "광휘의 행로"}
        self.requirements = [
            {
                "requirement_id": "requirement_1",
                "subject": "광휘의 행로",
                "relation": "minimum_reputation",
                "entity_anchor": anchor,
            },
            {
                "requirement_id": "requirement_2",
                "subject": "광휘의 행로",
                "relation": "max_simultaneous_explorations",
                "entity_anchor": anchor,
            },
        ]

    def test_extracts_two_exact_korean_requirement_surfaces(self) -> None:
        question = (
            "광휘의 행로 탐사에 필요한 최소 명성과 "
            "동시에 진행할 수 있는 탐사 수는 어떻게 돼?"
        )
        result = extract_entity_coordinated_surfaces(question, self.requirements)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            [row["surface"] for row in result["requirement_surfaces"]],
            ["탐사에 필요한 최소 명성", "동시에 진행할 수 있는 탐사 수"],
        )
        self.assertTrue(
            all(row["exact_question_substring"] for row in result["requirement_surfaces"])
        )
        self.assertEqual(result["domain_keyword_rule_count"], 0)

    def test_requires_one_verified_shared_entity_anchor(self) -> None:
        rows = copy.deepcopy(self.requirements)
        rows[1]["entity_anchor"] = {"phrase": "다른 기능"}
        self.assertIsNone(
            extract_entity_coordinated_surfaces(
                "광휘의 행로 최소 명성과 탐사 수는?", rows
            )
        )

    def test_accepts_identical_runtime_planner_subject_without_anchor_field(self) -> None:
        requirements = [
            {
                "requirement_id": "requirement_1",
                "subject": "던파ON",
                "relation": "applied_at",
            },
            {
                "requirement_id": "requirement_2",
                "subject": "던파ON",
                "relation": "download_started_at",
            },
        ]

        result = extract_entity_coordinated_surfaces(
            "던파ON의 2.0.19 적용 시점과 다운로드 시작 시각은 어떻게 돼?",
            requirements,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result["entity_resolution"],
            "shared_planner_subject_exact_question_match",
        )
        self.assertEqual(
            [row["surface"] for row in result["requirement_surfaces"]],
            ["2.0.19 적용 시점", "다운로드 시작 시각"],
        )

    def test_normalizes_runtime_planner_underscore_subject_for_question_match(self) -> None:
        requirements = [
            {
                "requirement_id": "requirement_1",
                "subject": "트리니티_랭킹",
                "relation": "노출_순위_범위",
            },
            {
                "requirement_id": "requirement_2",
                "subject": "트리니티_랭킹",
                "relation": "갱신_주기",
            },
        ]

        result = extract_entity_coordinated_surfaces(
            "트리니티 랭킹의 노출 순위 범위와 갱신 주기는 어떻게 돼?",
            requirements,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["entity_phrase"], "트리니티 랭킹")

    def test_live_planner_shape_passes_anchor_to_surface_query_end_to_end(self) -> None:
        entity_index = build_official_entity_index(
            [
                {
                    "document_id": "doc-dnf-on",
                    "source_id": "dnf_update",
                    "title": "던파ON",
                }
            ],
            [],
        )
        planned = [
            {
                "requirement_id": "requirement_1",
                "subject": "던파ON",
                "relation": "applied_at",
            },
            {
                "requirement_id": "requirement_2",
                "subject": "던파ON",
                "relation": "download_started_at",
            },
        ]
        question = "던파ON의 2.0.19 적용 시점과 다운로드 시작 시각은 어떻게 돼?"

        anchored = anchor_requirements(question, planned, entity_index)
        result = extract_entity_coordinated_surfaces(question, anchored)

        self.assertTrue(all("entity_anchor" in row for row in anchored))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["entity_resolution"], "verified_entity_anchor")
        scoring = build_surface_scoring_requirements(anchored, result)
        self.assertEqual(scoring[0]["subject"], "던파ON")
        self.assertEqual(scoring[0]["relation"], "2.0.19 적용 시점")
        self.assertEqual(scoring[0]["surface_query"], "던파ON 2.0.19 적용 시점")

    def test_does_not_guess_when_more_than_one_coordination_boundary_exists(self) -> None:
        self.assertIsNone(
            extract_entity_coordinated_surfaces(
                "광휘의 행로 최소 명성과 탐사 수와 보상은?", self.requirements
            )
        )

    def test_scoring_view_preserves_original_requirements(self) -> None:
        question = (
            "광휘의 행로 탐사에 필요한 최소 명성과 "
            "동시에 진행할 수 있는 탐사 수는 어떻게 돼?"
        )
        original = copy.deepcopy(self.requirements)
        extraction = extract_entity_coordinated_surfaces(question, self.requirements)
        assert extraction is not None
        scoring = build_surface_scoring_requirements(self.requirements, extraction)
        self.assertEqual(self.requirements, original)
        self.assertEqual(scoring[0]["subject"], "광휘의 행로")
        self.assertEqual(scoring[0]["relation"], "탐사에 필요한 최소 명성")
        self.assertEqual(
            scoring[0]["surface_query"], "광휘의 행로 탐사에 필요한 최소 명성"
        )
        self.assertEqual(scoring[0]["surface_query_entity"], "광휘의 행로")
        self.assertEqual(
            scoring[0]["surface_query_attribute"], "탐사에 필요한 최소 명성"
        )
        self.assertEqual(scoring[0]["planner_relation"], "minimum_reputation")


if __name__ == "__main__":
    unittest.main()
