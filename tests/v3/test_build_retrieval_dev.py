from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.v3.build_retrieval_dev import (
    EXPECTED_SOURCE_IDS,
    audit_rows,
    build_dev_rows,
    freeze_json,
    immutable_write,
    jsonl_bytes,
    read_jsonl,
    sha256_bytes,
    sha256_file,
)


SEED_SPEC = Path(
    "data/v3/evaluation/"
    "retrieval_dev_seed_spec_a625cc01df6fe746f104e2b868dc7ddcd49fa50ce8350c202f20cda1950e113b.jsonl"
)
CHUNKS = Path(
    "data/v3/chunks/"
    "chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DOCUMENTS = Path(
    "data/v3/normalized/"
    "documents_dnf_official_detail_v3.1_d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
LEGACY_PATHS = {
    "domain": Path("data/processed/domain_eval_set_expanded.jsonl"),
    "fresh": Path("data/processed/fresh_paraphrase_eval_set.jsonl"),
    "human_partial": Path("data/processed/partial_dev_human_v1.jsonl"),
    "official": Path("data/processed/official_eval_set.jsonl"),
}
FROZEN_DEV = Path(
    "data/v3/evaluation/"
    "retrieval_dev_v3.1_b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/evaluation/"
    "retrieval_dev_manifest_bb5a858702d8b8c0c267f35309db75221f8e9d5515e30f34b4e6b9dfb17dcec3.json"
)
FROZEN_REPORT_JSON = Path(
    "reports/v3/"
    "retrieval_dev_set_7dc0075638afbe0803ae0926e479ba1cb0050cedc53b224026a0ced5800025be.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "retrieval_dev_set_faf4e2aa58417ab769734aeb8983fba6998a2bf698bc23f44a477b69f2176689.md"
)


class BuildRetrievalDevTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seeds = read_jsonl(SEED_SPEC)
        cls.chunks = read_jsonl(CHUNKS)
        cls.documents = read_jsonl(DOCUMENTS)
        cls.legacy_sources = {
            role: (path.as_posix(), read_jsonl(path))
            for role, path in LEGACY_PATHS.items()
        }
        cls.rows = build_dev_rows(
            cls.seeds, cls.chunks, cls.documents, cls.legacy_sources
        )

    def test_actual_seed_build_is_deterministic_and_matches_frozen_dev(self) -> None:
        reversed_rows = build_dev_rows(
            self.seeds,
            list(reversed(self.chunks)),
            list(reversed(self.documents)),
            self.legacy_sources,
        )

        self.assertEqual(self.rows, reversed_rows)
        self.assertEqual(len(self.seeds), 63)
        self.assertEqual(sha256_file(SEED_SPEC), SEED_SPEC.stem.rsplit("_", 1)[1])
        self.assertEqual(
            sha256_bytes(jsonl_bytes(self.rows)), FROZEN_DEV.stem.rsplit("_", 1)[1]
        )
        self.assertEqual(self.rows, read_jsonl(FROZEN_DEV))

    def test_actual_composition_and_leakage_gates_pass(self) -> None:
        audit = audit_rows(self.rows)

        self.assertTrue(audit["gate_pass"])
        self.assertEqual(audit["answerability_counts"], {"false": 8, "partial": 8, "true": 47})
        self.assertEqual(set(audit["source_counts"]), EXPECTED_SOURCE_IDS)
        self.assertEqual(audit["multi_evidence_count"], 4)
        self.assertGreaterEqual(audit["nondefault_policy_count"], 4)
        self.assertTrue(all(not row["training_allowed"] for row in self.rows))
        self.assertTrue(all(not row["final_benchmark_eligible"] for row in self.rows))

    def test_evidence_groups_are_parent_consistent_and_policy_controls_are_safe(self) -> None:
        chunk_index = {row["chunk_id"]: row for row in self.chunks}
        for row in self.rows:
            for group in row["evidence_groups"]:
                parents = {
                    chunk_index[chunk_id]["parent_document_id"]
                    for chunk_id in group["acceptable_chunk_ids"]
                }
                self.assertEqual(parents, set(group["document_ids"]))
                self.assertEqual(len(parents), 1)
                for chunk_id in group["acceptable_chunk_ids"]:
                    self.assertIn(
                        group["evidence_span"],
                        " ".join(chunk_index[chunk_id]["display_text"].split()),
                    )
            if {"expired", "superseded"} & set(row["target_statuses"]):
                self.assertFalse(row["query_policy"]["default_exposure_only"])
            if row["query_kind"] == "preview_control":
                self.assertFalse(row["query_policy"]["default_exposure_only"])

    def test_direct_fixture_rejects_evidence_not_present_in_chunk(self) -> None:
        chunks = [
            {
                "chunk_id": "chunk_1",
                "parent_document_id": "doc_1",
                "display_text": "실제 본문",
                "source_id": "dnf_notice",
                "status": "current",
                "default_exposure": True,
                "review_required": False,
            }
        ]
        documents = [
            {
                "document_id": "doc_1",
                "source_id": "dnf_notice",
                "status": "current",
                "default_exposure": True,
            }
        ]
        seeds = [
            {
                "seed_id": "bad_direct",
                "kind": "direct",
                "question": "질문",
                "intent": "notice",
                "answerability": "true",
                "evidence_groups": [
                    {"evidence_span": "없는 근거", "chunk_ids": ["chunk_1"]}
                ],
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "direct evidence mismatch"):
            build_dev_rows(seeds, chunks, documents, {})

    def test_content_addressed_write_is_reproducible_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path, first_hash = freeze_json(root, "fixture", {"b": 2, "a": 1})
            second_path, second_hash = freeze_json(root, "fixture", {"a": 1, "b": 2})

            self.assertEqual(first_path, second_path)
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(sha256_file(first_path), first_hash)
            with self.assertRaisesRegex(RuntimeError, "immutable artifact collision"):
                immutable_write(first_path, b"changed\n")


class FrozenRetrievalDevArtifactTest(unittest.TestCase):
    def test_frozen_artifact_hashes_and_manifest_decisions(self) -> None:
        for path in (SEED_SPEC, FROZEN_DEV, FROZEN_MANIFEST, FROZEN_REPORT_JSON, FROZEN_REPORT_MD):
            self.assertEqual(sha256_file(path), path.stem.rsplit("_", 1)[1])

        manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        report = json.loads(FROZEN_REPORT_JSON.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dev_set"]["sha256"], sha256_file(FROZEN_DEV))
        self.assertEqual(manifest["inputs"]["seed_spec"]["sha256"], sha256_file(SEED_SPEC))
        self.assertTrue(manifest["audit"]["gate_pass"])
        self.assertFalse(manifest["training_allowed"])
        self.assertFalse(manifest["final_benchmark_eligible"])
        self.assertEqual(report["decision"]["retrieval_ab_entry"], "GO")
        self.assertEqual(report["decision"]["hybrid_promotion"], "NOT_RUN")
        self.assertEqual(report["decision"]["final_benchmark"], "NO-GO")


if __name__ == "__main__":
    unittest.main()
