from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from src.v3.run_unified_runtime import (
    PARTIAL_DISCLAIMER,
    build_abstention_response,
    build_single_runtime_response,
    freeze_unified_runtime,
    route_signature,
)


def _route(*, answerability: str = "true") -> dict[str, object]:
    return {
        "intent": "account_policy",
        "source_ids": ["dnf_account_policy"],
        "source_kinds": ["account_policy"],
        "time_scope": "current",
        "temporal_as_of": None,
        "default_exposure_only": True,
        "allowed_statuses": ["current", "upcoming"],
        "needs_decomposition": False,
        "needs_clarification": False,
        "route_action": "retrieve",
        "answerability": answerability,
        "answerability_reason": "official_document_fact_request"
        if answerability == "true"
        else "official_fact_plus_personal_judgment",
    }


def _selected() -> dict[str, object]:
    return {
        "selector_version": "fixture",
        "selected_rank": 1,
        "retrieval_rank": 1,
        "chunk_id": "chunk_current",
        "parent_document_id": "doc_current",
        "source_id": "dnf_account_policy",
        "source_kind": "account_policy",
        "status": "current",
        "default_exposure": True,
        "review_required": False,
        "heading_path": [],
        "chunk_type": "section",
        "display_text": "이용제한 데이터는 90일간 보유합니다.",
        "query_token_coverage": 1.0,
        "selector_score": 1.0,
        "selection_reason": "fixture",
        "guardrail_injected": False,
    }


class UnifiedRuntimeRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dev = {
            "dev_id": "dev_1",
            "question": "이용제한 데이터 보관기간은?",
            "answerability": "true",
        }
        self.documents = {
            "doc_current": {
                "document_id": "doc_current",
                "lineage_id": "policy",
                "revision_id": "rev_current",
                "source_id": "dnf_account_policy",
                "source_kind": "account_policy",
                "status": "current",
                "default_exposure": True,
                "valid_from": "2026-06-01",
                "valid_to": None,
            }
        }

    def test_route_signature_uses_only_runtime_contract_fields(self) -> None:
        route = _route()
        decorated = {**route, "routing_signals": {"diagnostic": True}}
        self.assertEqual(route_signature(route), route_signature(decorated))
        changed = {**route, "time_scope": "historical"}
        self.assertNotEqual(route_signature(route), route_signature(changed))

    def test_single_retrieve_builds_verified_exact_quote_response(self) -> None:
        response = build_single_runtime_response(
            self.dev,
            {
                "route": _route(),
                "temporal_resolution": {
                    "selected_document_id": "doc_current",
                    "selected_revision_id": "rev_current",
                },
                "hits": [{"chunk_id": "chunk_current"}],
            },
            [_selected()],
            self.documents,
        )

        self.assertEqual(response["response_type"], "verified_extractive_answer")
        self.assertEqual(response["runtime_status"], "success")
        self.assertTrue(response["verification"]["verified"])
        self.assertEqual(len(response["answer_plan"]["claims"]), 1)

    def test_partial_response_keeps_official_fact_disclaimer(self) -> None:
        dev = {**self.dev, "answerability": "partial"}
        response = build_single_runtime_response(
            dev,
            {
                "route": _route(answerability="partial"),
                "temporal_resolution": {
                    "selected_document_id": "doc_current",
                    "selected_revision_id": "rev_current",
                },
                "hits": [{"chunk_id": "chunk_current"}],
            },
            [_selected()],
            self.documents,
        )

        self.assertEqual(response["response_type"], "partial_official_fact")
        self.assertTrue(response["rendered_answer"].startswith(PARTIAL_DISCLAIMER))

    def test_reject_and_realtime_routes_never_expose_corpus_evidence(self) -> None:
        for action in ("reject", "realtime_api"):
            route = {
                **_route(),
                "route_action": action,
                "answerability": "false",
                "answerability_reason": "unsupported",
                "source_ids": [],
                "source_kinds": [],
            }
            response = build_abstention_response(self.dev, route)
            self.assertEqual(response["runtime_status"], "abstained")
            self.assertEqual(response["citation_chunk_ids"], [])
            self.assertIsNone(response["answer_plan"])


class UnifiedRuntimeArtifactTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    CASES_SHA = "f28e2fbfb768c901dc4f1079f262252d645a74c7e4ee494180c2879e528f7789"
    MANIFEST_SHA = "7f9d747c65960db5985c2ddf07592e09f0f82053b41db2801ce117151ac032c3"

    def test_full_replay_is_content_addressed_and_reproducible(self) -> None:
        result = freeze_unified_runtime(root=self.ROOT)
        self.assertEqual(result["cases_sha256"], self.CASES_SHA)
        self.assertEqual(result["manifest_sha256"], self.MANIFEST_SHA)

        cases_path = Path(result["cases_path"])
        manifest_path = Path(result["manifest_path"])
        self.assertEqual(
            hashlib.sha256(cases_path.read_bytes()).hexdigest(), self.CASES_SHA
        )
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(), self.MANIFEST_SHA
        )
        rows = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 63)
        self.assertEqual(manifest["cases"]["row_count"], 63)
        self.assertEqual([row["query_ordinal"] for row in rows], list(range(63)))

        abstained = [
            row for row in rows if row["response"]["runtime_status"] == "abstained"
        ]
        self.assertEqual(len(abstained), 8)
        self.assertTrue(
            all(not row["response"]["citation_chunk_ids"] for row in abstained)
        )


if __name__ == "__main__":
    unittest.main()
