from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from apply_citation_policy import force_reranker_top1  # noqa: E402


class CitationPolicyTests(unittest.TestCase):
    def test_uses_top1_only_for_predicted_answerable_rows(self) -> None:
        report = {
            "details": [
                {
                    "parsed_answerability": "true",
                    "retrieved_chunk_ids": ["top1", "top2"],
                    "expected_chunk_ids": ["top1"],
                    "parsed_citations": ["top2"],
                },
                {
                    "parsed_answerability": "false",
                    "retrieved_chunk_ids": ["top1"],
                    "expected_chunk_ids": [],
                    "parsed_citations": ["top1"],
                },
            ]
        }

        output = force_reranker_top1(report)

        self.assertEqual(output["details"][0]["parsed_citations"], ["top1"])
        self.assertTrue(output["details"][0]["parsed_citation_hit"])
        self.assertEqual(output["details"][1]["parsed_citations"], [])
        self.assertEqual(output["summary"]["changed_rows"], 2)


if __name__ == "__main__":
    unittest.main()
