from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.io_utils import read_jsonl
from src.v3.build_bm25 import SearchPolicy
from src.v3.build_corpus import file_sha256
from src.v3.build_dense_pilot import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_CHUNK_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DOCUMENTS,
    DEFAULT_PILOT_SELECTION,
    build_dense_pilot_artifacts,
    search_dense,
    select_dense_pilot_chunks,
)


BUILT_AT = "2026-07-18T01:51:13+09:00"
FROZEN_SELECTION = Path(
    "data/v3/indexes/"
    "dense_pilot_selection_fdfdde3e765a5e68a093127f235f6d5e41168ea9c8e0d54f60ea74fe121c1e8e.jsonl"
)
FROZEN_METADATA = Path(
    "data/v3/indexes/"
    "dense_pilot_metadata_948948873ff42c11abd194f6d13a2b2dc3abde06db199ab5e98afcd9b7337c89.jsonl"
)
FROZEN_EMBEDDINGS = Path(
    "data/v3/indexes/"
    "dense_pilot_embeddings_3d75d86d51c5f7ff4a00c09526932d4ada5eac88ed1b9505b6e55c9259d48a15.f32"
)
FROZEN_MANIFEST = Path(
    "data/v3/indexes/"
    "dense_pilot_manifest_3494f45113fe2f0e077becc3c905893d07869e4c1cb922511872676aec6d4438.json"
)
FROZEN_DIAGNOSTICS = Path(
    "data/v3/retrieval/"
    "dense_pilot_diagnostics_0f79f78369115feeed1773573b2f771039761929db2bec0cf158321df43dacea.jsonl"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "dense_pilot_f1640c1117d7a7d210fdb56be4b1d13898f8c81a46b0c8e63f77280e67b36db9.json"
)


class BuildDensePilotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = read_jsonl(DEFAULT_CHUNKS)
        cls.pilot_selection = read_jsonl(DEFAULT_PILOT_SELECTION)

    def test_actual_pilot_selection_is_deterministic_and_stratified(self) -> None:
        first = select_dense_pilot_chunks(self.chunks, self.pilot_selection)
        second = select_dense_pilot_chunks(
            list(reversed(self.chunks)), list(reversed(self.pilot_selection))
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 467)
        self.assertEqual(len({row["parent_document_id"] for row in first}), 63)
        self.assertEqual(len({row["source_id"] for row in first}), 8)
        self.assertEqual(
            {row["status"] for row in first},
            {"current", "expired", "superseded", "unknown"},
        )
        self.assertEqual(sum(row["default_exposure"] for row in first), 272)
        self.assertEqual(sum(row["offset_source"] == "visual_ocr" for row in first), 22)

    def test_dense_search_applies_same_default_and_historical_filters(self) -> None:
        embeddings = np.asarray(
            [[1.0, 0.0], [0.0, 1.0], [0.8, 0.6]], dtype=np.float32
        )
        metadata = [
            {
                "chunk_id": "current",
                "source_id": "dnf_notice",
                "status": "current",
                "default_exposure": True,
                "review_required": False,
                "valid_from": None,
                "valid_to": None,
            },
            {
                "chunk_id": "expired",
                "source_id": "dnf_notice",
                "status": "expired",
                "default_exposure": False,
                "review_required": False,
                "valid_from": None,
                "valid_to": None,
            },
            {
                "chunk_id": "visual",
                "source_id": "dnf_notice",
                "status": "current",
                "default_exposure": False,
                "review_required": True,
                "valid_from": None,
                "valid_to": None,
            },
        ]

        default_hits = search_dense(embeddings, metadata, np.asarray([0.0, 1.0]))
        expired_hits = search_dense(
            embeddings,
            metadata,
            np.asarray([0.0, 1.0]),
            policy=SearchPolicy(
                default_exposure_only=False,
                allowed_statuses=("expired",),
            ),
        )
        visual_hits = search_dense(
            embeddings,
            metadata,
            np.asarray([0.8, 0.6]),
            policy=SearchPolicy(
                default_exposure_only=False,
                allowed_statuses=("current",),
                include_review_required=True,
            ),
        )

        self.assertEqual([row["chunk_id"] for row in default_hits], ["current"])
        self.assertEqual([row["chunk_id"] for row in expired_hits], ["expired"])
        self.assertEqual(visual_hits[0]["chunk_id"], "visual")

    def test_override_freeze_is_content_addressed_and_reproducible(self) -> None:
        rng = np.random.default_rng(7)
        embeddings = rng.normal(size=(467, 4)).astype(np.float32)
        embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
        diagnostic_rows = [
            {"case_id": f"case_{index:02d}", "kind": "fixture"}
            for index in range(12)
        ]
        diagnostic_summary = {
            "default_title_lookup_cases": 8,
            "dense_default_title_hit_at_5": 8,
            "bm25_default_title_hit_at_5": 8,
            "historical_and_visual_control_cases": 4,
            "dense_control_hit_at_5": 4,
            "bm25_control_hit_at_5": 4,
            "dense_default_policy_violations": 0,
            "mean_top5_chunk_overlap": 1.0,
            "diagnostic_decision": "GO",
        }
        model_info = {
            "model_name": "fixture",
            "model_revision": "fixture",
            "sentence_transformers_version": "fixture",
            "torch_version": "fixture",
            "numpy_version": np.__version__,
            "device": "cpu",
            "device_name": "cpu",
            "max_sequence_length": 2048,
            "batch_size": 2,
            "embedding_dimension": 4,
            "embedding_dtype": "float32",
            "normalize_embeddings": True,
            "similarity": "cosine_via_normalized_dot_product",
            "repeat_encode_rows": 16,
            "repeat_encode_max_abs_diff": 0.0,
        }
        token_measurement = {
            "row_count": 467,
            "token_length": {
                "min": 1,
                "p50": 10,
                "p90": 20,
                "p95": 20,
                "p99": 20,
                "max": 20,
                "mean": 10.0,
            },
            "requested_max_sequence_length": 2048,
            "over_requested_max": 0,
            "truncation_detected": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kwargs = {
                "built_at": "2026-07-18T02:00:00+09:00",
                "chunks_path": DEFAULT_CHUNKS,
                "chunk_manifest_path": DEFAULT_CHUNK_MANIFEST,
                "pilot_selection_path": DEFAULT_PILOT_SELECTION,
                "documents_path": DEFAULT_DOCUMENTS,
                "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
                "index_dir": root / "indexes",
                "retrieval_dir": root / "retrieval",
                "report_dir": root / "reports",
                "embeddings_override": embeddings,
                "diagnostics_override": (diagnostic_rows, diagnostic_summary),
                "model_info_override": model_info,
                "token_measurement_override": token_measurement,
            }

            first = build_dense_pilot_artifacts(**kwargs)
            second = build_dense_pilot_artifacts(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["full_dense_index_decision"], "GO")
            self.assertEqual(
                file_sha256(Path(first["embedding_path"])), first["embedding_sha256"]
            )
            self.assertEqual(
                file_sha256(Path(first["manifest_path"])), first["manifest_sha256"]
            )
            self.assertEqual(
                file_sha256(Path(first["report_json_path"])), first["report_sha256"]
            )


class FrozenDensePilotArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selection = read_jsonl(FROZEN_SELECTION)
        cls.metadata = read_jsonl(FROZEN_METADATA)
        cls.manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        cls.diagnostics = read_jsonl(FROZEN_DIAGNOSTICS)
        cls.report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        cls.embeddings = np.fromfile(FROZEN_EMBEDDINGS, dtype="<f4").reshape(467, 1024)

    def test_actual_dense_pilot_artifacts_pass_binary_alignment_filter_and_token_gates(self) -> None:
        for path in (
            FROZEN_SELECTION,
            FROZEN_METADATA,
            FROZEN_EMBEDDINGS,
            FROZEN_MANIFEST,
            FROZEN_DIAGNOSTICS,
            FROZEN_REPORT,
        ):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])
        self.assertEqual(len(self.selection), 467)
        self.assertEqual(len(self.metadata), 467)
        self.assertEqual(len(self.diagnostics), 12)
        self.assertEqual(self.embeddings.shape, (467, 1024))
        self.assertTrue(np.isfinite(self.embeddings).all())
        norms = np.linalg.norm(self.embeddings, axis=1)
        self.assertTrue(np.all(np.abs(norms - 1.0) <= 1e-5))
        self.assertEqual(
            [row["chunk_id"] for row in self.selection],
            [row["chunk_id"] for row in self.metadata],
        )
        self.assertEqual(
            [row["ordinal"] for row in self.metadata], list(range(467))
        )
        self.assertTrue(
            all(value is True or value == 0 for value in self.report["gates"].values())
        )
        self.assertEqual(self.report["full_dense_index_decision"], "GO")
        self.assertEqual(self.report["model"]["embedding_dimension"], 1024)
        self.assertEqual(self.report["model"]["max_sequence_length"], 2048)
        self.assertLessEqual(
            self.report["model"]["repeat_encode_max_abs_diff"], 1e-6
        )
        self.assertEqual(self.report["token_measurement"]["over_requested_max"], 0)
        self.assertEqual(self.report["diagnostic"]["dense_default_title_hit_at_5"], 8)
        self.assertEqual(self.report["diagnostic"]["dense_control_hit_at_5"], 4)
        self.assertEqual(self.report["diagnostic"]["dense_default_policy_violations"], 0)
        self.assertEqual(self.manifest["embeddings"]["sha256"], file_sha256(FROZEN_EMBEDDINGS))

    def test_actual_dense_pilot_refreeze_is_reproducible_without_model_reload(self) -> None:
        kwargs = {
            "built_at": BUILT_AT,
            "chunks_path": DEFAULT_CHUNKS,
            "chunk_manifest_path": DEFAULT_CHUNK_MANIFEST,
            "pilot_selection_path": DEFAULT_PILOT_SELECTION,
            "documents_path": DEFAULT_DOCUMENTS,
            "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
            "index_dir": Path("data/v3/indexes"),
            "retrieval_dir": Path("data/v3/retrieval"),
            "report_dir": Path("reports/v3"),
            "embeddings_override": self.embeddings,
            "diagnostics_override": (
                self.diagnostics,
                self.report["diagnostic"],
            ),
            "model_info_override": self.report["model"],
            "token_measurement_override": self.report["token_measurement"],
        }

        first = build_dense_pilot_artifacts(**kwargs)
        second = build_dense_pilot_artifacts(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["selection_sha256"], file_sha256(FROZEN_SELECTION))
        self.assertEqual(first["metadata_sha256"], file_sha256(FROZEN_METADATA))
        self.assertEqual(first["embedding_sha256"], file_sha256(FROZEN_EMBEDDINGS))
        self.assertEqual(first["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(first["diagnostics_sha256"], file_sha256(FROZEN_DIAGNOSTICS))
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_REPORT))


if __name__ == "__main__":
    unittest.main()
