from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from make_contextual_prefix_chunks import add_contextual_prefix, build_contextual_prefix  # noqa: E402


class ContextualPrefixTests(unittest.TestCase):
    def test_uses_only_stable_available_metadata(self) -> None:
        prefix = build_contextual_prefix(
            {
                "doc_type": "event",
                "published_at": "2026-07-02",
                "effective_start": "2026-07-02",
                "effective_end": "2026-07-30",
                "section": "보상 > 누적 보상",
                "metadata": {"collected_at": "unstable", "doc_no": "123"},
            }
        )

        self.assertEqual(
            prefix,
            "문서 유형: 이벤트\n"
            "게시일: 2026-07-02\n"
            "적용 기간: 2026-07-02 ~ 2026-07-30\n"
            "섹션: 보상 > 누적 보상",
        )
        self.assertNotIn("collected_at", prefix)
        self.assertNotIn("123", prefix)

    def test_preserves_identity_and_appends_original_text(self) -> None:
        original = {
            "doc_id": "doc__chunk_001",
            "doc_type": "game_guide",
            "title": "장비 강화",
            "text": "강화에는 라이언 코어가 필요합니다.",
        }

        contextual = add_contextual_prefix(original)

        self.assertEqual(contextual["doc_id"], original["doc_id"])
        self.assertEqual(contextual["title"], original["title"])
        self.assertTrue(contextual["text"].endswith(original["text"]))
        self.assertNotIn("장비 강화", contextual["contextual_prefix"])
        self.assertEqual(original["text"], "강화에는 라이언 코어가 필요합니다.")

    def test_rejects_empty_chunk_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty text"):
            add_contextual_prefix({"doc_id": "empty", "doc_type": "notice", "text": ""})


if __name__ == "__main__":
    unittest.main()
