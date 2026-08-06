from __future__ import annotations

import unittest

from src.v3.minimal_prompt_refs import compact_prompt_evidence_refs


class MinimalPromptRefsTests(unittest.TestCase):
    def test_sparse_refs_are_compacted_without_changing_coordinates(self) -> None:
        units = {
            "E6": {
                "evidence_ref": "E6",
                "chunk_id": "chunk-a",
                "start_char": 10,
                "end_char": 20,
                "context_refs": [],
                "continuation_refs": ["E210"],
            },
            "E210": {
                "evidence_ref": "E210",
                "chunk_id": "chunk-b",
                "start_char": 30,
                "end_char": 40,
                "context_refs": ["E6", "E119"],
                "continuation_refs": [],
            },
        }
        prompt, compact, mapping = compact_prompt_evidence_refs(
            "header\nE6\ttemporal_roles=none\t가격\n"
            "E210\ttemporal_roles=none\t거래타입",
            units,
        )
        self.assertEqual(mapping, {"E6": "E1", "E210": "E2"})
        self.assertIn("E1\ttemporal_roles=none\t가격", prompt)
        self.assertIn("E2\ttemporal_roles=none\t거래타입", prompt)
        self.assertEqual(compact["E1"]["chunk_id"], "chunk-a")
        self.assertEqual(compact["E1"]["start_char"], 10)
        self.assertEqual(compact["E1"]["continuation_refs"], ["E2"])
        self.assertEqual(compact["E2"]["context_refs"], ["E1"])
        self.assertEqual(compact["E2"]["original_evidence_ref"], "E210")

    def test_missing_prompt_ref_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "prompt and visible evidence refs differ",
        ):
            compact_prompt_evidence_refs(
                "E1\t근거",
                {
                    "E1": {"evidence_ref": "E1"},
                    "E2": {"evidence_ref": "E2"},
                },
            )


if __name__ == "__main__":
    unittest.main()
