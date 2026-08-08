from __future__ import annotations

import unittest
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from src.v3.harden_detail_parsers import structured_text_hardened


FIXTURE = Path(__file__).resolve().parent / "fixtures/nested_img_void_tag.html"


class NestedImageVoidTagTest(unittest.TestCase):
    def test_nested_images_do_not_crash_or_drop_meaningful_alt(self) -> None:
        soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
        node = soup.find(id="fixture")
        self.assertIsInstance(node, Tag)

        reparsed = BeautifulSoup(str(node), "html.parser")
        root = reparsed.find(id="fixture")
        self.assertIsInstance(root, Tag)
        images = list(root.find_all("img"))
        self.assertIn(images[3], images[2].descendants)

        text, *_ = structured_text_hardened(node)

        self.assertIn("설명 있는 이미지", text)


if __name__ == "__main__":
    unittest.main()
