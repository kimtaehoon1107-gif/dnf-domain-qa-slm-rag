import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_tuned_slm_smoke import format_rag_only_generation, parse_generated_fields  # noqa: E402


class GenerationComparisonModeTests(unittest.TestCase):
    def test_rag_only_generation_uses_shared_structured_schema(self):
        contexts = [
            {
                "doc_id": "official_notice_1__chunk_001",
                "doc_type": "notice",
                "distance": 0.2,
                "text": "점검은 오전 6시부터 오전 9시까지 진행됩니다.",
            }
        ]

        generated = format_rag_only_generation("점검 시간이 언제야?", contexts)
        parsed = parse_generated_fields(generated)

        self.assertEqual(parsed["parsed_answerability"], "true")
        self.assertEqual(parsed["parsed_citations"], ["official_notice_1__chunk_001"])
        self.assertIn("오전 6시", parsed["parsed_answer"])

    def test_rag_only_refusal_has_no_citation(self):
        generated = format_rag_only_generation("내 계정 제재 상태 알려줘", [])
        parsed = parse_generated_fields(generated)

        self.assertEqual(parsed["parsed_answerability"], "false")
        self.assertEqual(parsed["parsed_citations"], [])


if __name__ == "__main__":
    unittest.main()
