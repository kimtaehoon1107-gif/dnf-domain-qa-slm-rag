from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy
from src.v3.build_corpus import file_sha256
from src.v3.evaluate_retrieval import policy_from_dev
from src.v3.retrieve_v3 import load_runtime_artifacts, retrieve_with_embedding
from src.v3.select_evidence import select_evidence
from src.v3.validate_retrieval_runtime import (
    DEFAULT_ANNOTATION_MANIFEST,
    DEFAULT_BM25_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DENSE_MANIFEST,
    DEFAULT_DEV_SET,
    DEFAULT_DOCUMENTS,
    DEFAULT_EXPECTED_RESULTS,
    DEFAULT_QUERY_EMBEDDINGS,
    DEFAULT_RUNTIME_SOURCE,
    build_and_freeze,
    validate_runtime_replay,
)


FROZEN_REPLAY = Path(
    "data/v3/retrieval/"
    "retrieval_runtime_replay_bff9fe0bc935b960840fb186ce91ae3df43d6d5c2f7df7fd73247ebea9e4a37e.jsonl"
)
FROZEN_MANIFEST = Path(
    "data/v3/retrieval/"
    "retrieval_runtime_manifest_6605e9885a6c45d59d9852edc09ef0f93fcff427d8d29747e3d85ef8b7c94f65.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "retrieval_runtime_b646709174b72d36ed2ef70cd0228e623054bc9cab38e9fdace143af817c3f8f.json"
)
FROZEN_REPORT_MD = Path(
    "reports/v3/"
    "retrieval_runtime_157e6c99b4e8c64e9759481f3073c085034dc1ef29944a3090f24037ce73e6e6.md"
)


class RetrievalRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path.cwd()
        cls.dev = read_jsonl(DEFAULT_DEV_SET)
        cls.expected = read_jsonl(DEFAULT_EXPECTED_RESULTS)
        values = np.fromfile(DEFAULT_QUERY_EMBEDDINGS, dtype="<f4")
        cls.embeddings = values.reshape(len(cls.dev), 1024)
        cls.artifacts = load_runtime_artifacts(cls.root)

    def test_runtime_replays_all_frozen_top_twenty_rankings_exactly(self) -> None:
        replay = validate_runtime_replay(
            self.root, self.dev, self.embeddings, self.expected
        )

        self.assertEqual(len(replay), 63)
        self.assertTrue(all(row["top_10_exact_match"] for row in replay))
        self.assertTrue(all(row["top_20_exact_match"] for row in replay))
        self.assertTrue(all(row["first_mismatch_rank"] is None for row in replay))
        self.assertEqual(sum(row["structured_field_query"] for row in replay), 7)

    def test_default_policy_exposes_only_current_safe_documents(self) -> None:
        hits = retrieve_with_embedding(
            self.dev[1]["question"],
            self.embeddings[1],
            self.artifacts,
            top_k=20,
            policy=SearchPolicy(as_of="2026-07-18"),
        )

        self.assertEqual(len(hits), 20)
        self.assertTrue(all(row["status"] in {"current", "upcoming"} for row in hits))
        self.assertTrue(all(row["default_exposure"] for row in hits))
        self.assertTrue(all(not row["review_required"] for row in hits))
        self.assertTrue(all(row["canonical_url"] for row in hits))
        self.assertTrue(all(row["display_text"] for row in hits))

    def test_historical_policy_can_retrieve_superseded_revision(self) -> None:
        ordinal = next(
            index
            for index, row in enumerate(self.dev)
            if row["query_policy"]["allowed_statuses"] == ["superseded"]
        )
        hits = retrieve_with_embedding(
            self.dev[ordinal]["question"],
            self.embeddings[ordinal],
            self.artifacts,
            top_k=10,
            policy=policy_from_dev(self.dev[ordinal]),
        )

        self.assertTrue(hits)
        self.assertTrue(all(row["status"] == "superseded" for row in hits))
        self.assertTrue(all(not row["default_exposure"] for row in hits))

    def test_structured_guard_is_query_scoped(self) -> None:
        structured = retrieve_with_embedding(
            self.dev[0]["question"],
            self.embeddings[0],
            self.artifacts,
            top_k=10,
            policy=policy_from_dev(self.dev[0]),
        )
        plain = retrieve_with_embedding(
            self.dev[1]["question"],
            self.embeddings[1],
            self.artifacts,
            top_k=10,
            policy=policy_from_dev(self.dev[1]),
        )

        self.assertTrue(all(row["structured_field_query"] for row in structured))
        self.assertTrue(any(row["guardrail_injected"] for row in structured))
        self.assertTrue(all(not row["structured_field_query"] for row in plain))
        self.assertTrue(all(not row["guardrail_injected"] for row in plain))

    def test_actual_runtime_hits_feed_the_evidence_selector(self) -> None:
        hits = retrieve_with_embedding(
            self.dev[0]["question"],
            self.embeddings[0],
            self.artifacts,
            top_k=10,
            policy=policy_from_dev(self.dev[0]),
        )
        selected = select_evidence(
            self.dev[0]["question"], hits, self.artifacts.chunks_by_id
        )

        self.assertLessEqual(len(selected), 10)
        self.assertTrue(all(row["display_text"] for row in selected))
        self.assertTrue(any(row["guardrail_injected"] for row in selected))
        self.assertTrue(
            set(self.dev[0]["evidence_groups"][0]["acceptable_chunk_ids"])
            & {row["chunk_id"] for row in selected}
        )

    def test_invalid_query_top_k_and_embedding_are_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            retrieve_with_embedding(" ", self.embeddings[0], self.artifacts)
        with self.assertRaises(RuntimeError):
            retrieve_with_embedding("query", self.embeddings[0], self.artifacts, top_k=21)
        with self.assertRaises(RuntimeError):
            retrieve_with_embedding("query", np.zeros(10), self.artifacts)


class FrozenRetrievalRuntimeArtifactTest(unittest.TestCase):
    def test_frozen_hashes_and_decisions_are_preserved(self) -> None:
        for path in (FROZEN_REPLAY, FROZEN_MANIFEST, FROZEN_REPORT, FROZEN_REPORT_MD):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])

        report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["decision"]["runtime_entrypoint"], "GO")
        self.assertEqual(report["decision"]["development_retriever"], "GO")
        self.assertEqual(report["decision"]["annotation_human_review"], "PENDING")
        self.assertEqual(report["decision"]["final_benchmark"], "NO-GO")
        self.assertTrue(report["audit"]["gate_pass"])

    def test_actual_inputs_refreeze_to_identical_artifacts(self) -> None:
        result = build_and_freeze(
            Path.cwd(),
            DEFAULT_DEV_SET,
            DEFAULT_QUERY_EMBEDDINGS,
            DEFAULT_EXPECTED_RESULTS,
            DEFAULT_ANNOTATION_MANIFEST,
            DEFAULT_BM25_MANIFEST,
            DEFAULT_DENSE_MANIFEST,
            DEFAULT_CHUNKS,
            DEFAULT_DOCUMENTS,
            DEFAULT_RUNTIME_SOURCE,
        )

        self.assertEqual(result["replay_sha256"], file_sha256(FROZEN_REPLAY))
        self.assertEqual(result["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(result["report_sha256"], file_sha256(FROZEN_REPORT))
        self.assertEqual(result["report_markdown_sha256"], file_sha256(FROZEN_REPORT_MD))


if __name__ == "__main__":
    unittest.main()
