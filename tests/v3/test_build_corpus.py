from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.io_utils import read_jsonl
from src.v3.build_corpus import SourceSpec, build_corpus, file_sha256, stable_content_hash
from src.v3.schemas import (
    CORPUS_MANIFEST_REQUIRED_FIELDS,
    DOCUMENT_REQUIRED_FIELDS,
    RAW_SNAPSHOT_MANIFEST_ENTRY_REQUIRED_FIELDS,
    missing_required_fields,
)


def _raw_row(
    *,
    text: str,
    collected_at: str,
    source_url: str = "https://df.nexon.com/guide?no=1",
) -> dict:
    return {
        "doc_id": "legacy_1",
        "source_type": "official",
        "doc_type": "game_guide",
        "title": "테스트 가이드",
        "published_at": "2026-01-01",
        "effective_start": None,
        "effective_end": None,
        "source_url": source_url,
        "tags": ["official", "guide"],
        "text": text,
        "metadata": {
            "official_section": "guide",
            "guide_no": "1",
            "guide_category": "시스템",
            "guide_updated_at": "2026-01-01",
            "collected_at": collected_at,
        },
    }


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class BuildCorpusTest(unittest.TestCase):
    def test_builds_required_manifest_and_document_fields_without_mutating_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jsonl"
            row = _raw_row(text="원문 본문", collected_at="2026-01-02T03:04:05")
            _write_rows(source, [row])
            source_bytes_before = source.read_bytes()
            source_hash_before = file_sha256(source)

            result = build_corpus(
                [SourceSpec("test_docs", source, "legacy-test-parser")],
                snapshot_dir=root / "snapshots",
                normalized_dir=root / "normalized",
            )

            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            documents = read_jsonl(Path(result["normalized_path"]))
            entry = manifest["artifacts"][0]

            self.assertEqual(
                missing_required_fields(manifest, CORPUS_MANIFEST_REQUIRED_FIELDS), []
            )
            self.assertEqual(
                missing_required_fields(entry, RAW_SNAPSHOT_MANIFEST_ENTRY_REQUIRED_FIELDS), []
            )
            self.assertEqual(missing_required_fields(documents[0], DOCUMENT_REQUIRED_FIELDS), [])
            self.assertEqual(entry["row_count"], 1)
            self.assertEqual(entry["fetched_at"], "2026-01-02T03:04:05")
            self.assertEqual(entry["sha256"], source_hash_before)
            self.assertEqual(documents[0]["content_hash"], stable_content_hash(row))
            self.assertEqual(Path(entry["snapshot_path"]).read_bytes(), source_bytes_before)
            self.assertEqual(source.read_bytes(), source_bytes_before)
            self.assertEqual(file_sha256(source), source_hash_before)

    def test_hashes_and_ids_are_stable_across_repeated_builds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.jsonl"
            _write_rows(
                source,
                [_raw_row(text="안정적인 본문", collected_at="2026-01-02T03:04:05")],
            )
            spec = SourceSpec("test_docs", source, "legacy-test-parser")

            first = build_corpus(
                [spec],
                snapshot_dir=root / "snapshots",
                normalized_dir=root / "normalized",
            )
            second = build_corpus(
                [spec],
                snapshot_dir=root / "snapshots",
                normalized_dir=root / "normalized",
            )
            first_documents = read_jsonl(Path(first["normalized_path"]))
            second_documents = read_jsonl(Path(second["normalized_path"]))

            self.assertEqual(first["manifest_path"], second["manifest_path"])
            self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
            self.assertEqual(first["normalized_path"], second["normalized_path"])
            self.assertEqual(first["normalized_sha256"], second["normalized_sha256"])
            self.assertEqual(first_documents[0]["document_id"], second_documents[0]["document_id"])
            self.assertEqual(first_documents[0]["revision_id"], second_documents[0]["revision_id"])

    def test_same_url_and_content_deduplicate_while_changed_content_forms_revision_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_source = root / "old.jsonl"
            repeated_source = root / "repeated.jsonl"
            new_source = root / "new.jsonl"
            old_row = _raw_row(
                text="첫 본문",
                collected_at="2026-01-01T00:00:00",
                source_url="https://DF.NEXON.COM/guide?b=2&a=1#section",
            )
            repeated_row = _raw_row(
                text="첫 본문",
                collected_at="2026-02-01T00:00:00",
                source_url="https://df.nexon.com/guide?a=1&b=2",
            )
            new_row = _raw_row(
                text="수정 본문",
                collected_at="2026-03-01T00:00:00",
                source_url="https://df.nexon.com/guide?b=2&a=1",
            )
            _write_rows(old_source, [old_row])
            _write_rows(repeated_source, [repeated_row])
            _write_rows(new_source, [new_row])
            source_bytes_before = {
                path: path.read_bytes() for path in (old_source, repeated_source, new_source)
            }
            specs = [
                SourceSpec("old", old_source, "legacy-test-parser"),
                SourceSpec("repeated", repeated_source, "legacy-test-parser"),
                SourceSpec("new", new_source, "legacy-test-parser"),
            ]

            result = build_corpus(
                specs,
                snapshot_dir=root / "snapshots",
                normalized_dir=root / "normalized",
            )
            documents = read_jsonl(Path(result["normalized_path"]))

            self.assertEqual(result["source_row_count"], 3)
            self.assertEqual(result["document_count"], 2)
            self.assertEqual(result["deduplicated_observation_count"], 1)
            self.assertEqual(stable_content_hash(old_row), stable_content_hash(repeated_row))
            self.assertNotEqual(stable_content_hash(old_row), stable_content_hash(new_row))
            self.assertEqual(documents[0]["canonical_url"], documents[1]["canonical_url"])
            self.assertEqual(documents[0]["fetched_at"], "2026-02-01T00:00:00")
            self.assertEqual(documents[0]["status"], "superseded")
            self.assertIsNone(documents[0]["supersedes_document_id"])
            self.assertEqual(documents[1]["status"], "current")
            self.assertEqual(
                documents[1]["supersedes_document_id"], documents[0]["document_id"]
            )
            for path, content in source_bytes_before.items():
                self.assertEqual(path.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
