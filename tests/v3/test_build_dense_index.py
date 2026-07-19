from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.build_dense_index import (
    DEFAULT_BM25_MANIFEST,
    DEFAULT_CHUNK_MANIFEST,
    DEFAULT_CHUNKS,
    DEFAULT_DOCUMENTS,
    _load_bm25_index,
    audit_bm25_parity,
    build_dense_full_artifacts,
    build_dense_metadata,
)


BUILT_AT = "2026-07-18T11:58:00+09:00"
FROZEN_METADATA = Path(
    "data/v3/indexes/"
    "dense_full_metadata_0343e23130322d2db046eeb5212f8fe6ca3178456036e1873ca3401634998a46.jsonl"
)
FROZEN_EMBEDDINGS = Path(
    "data/v3/indexes/"
    "dense_full_embeddings_2c294cde018eefa354971029c240dd6fd5f2a30ead757441f6dadacea110b10d.f32"
)
FROZEN_MANIFEST = Path(
    "data/v3/indexes/"
    "dense_full_manifest_51074e7e337a64e94a7cc66c8dd7b8b3ed982bad0b3aa82e2e5f30fb84520349.json"
)
FROZEN_REPORT = Path(
    "reports/v3/"
    "dense_full_index_4200f191aecd861a9304c9047cf579295f1eec5c195c868df75803dd3948778f.json"
)


class BuildDenseFullTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = read_jsonl(DEFAULT_CHUNKS)
        cls.documents = read_jsonl(DEFAULT_DOCUMENTS)

    def test_actual_full_metadata_is_deterministic_and_complete(self) -> None:
        first = build_dense_metadata(self.chunks, self.documents)
        second = build_dense_metadata(
            list(reversed(self.chunks)), list(reversed(self.documents))
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 3599)
        self.assertEqual(len({row["parent_document_id"] for row in first}), 980)
        self.assertEqual(len({row["source_id"] for row in first}), 8)
        self.assertEqual(
            {row["status"] for row in first},
            {"current", "expired", "superseded", "unknown"},
        )
        self.assertEqual(sum(row["default_exposure"] for row in first), 2527)
        self.assertEqual(sum(row["offset_source"] == "visual_ocr" for row in first), 22)
        self.assertEqual([row["ordinal"] for row in first], list(range(3599)))

    def test_actual_bm25_metadata_and_filter_parity(self) -> None:
        metadata = build_dense_metadata(self.chunks, self.documents)
        bm25_index, _, _ = _load_bm25_index(DEFAULT_BM25_MANIFEST)

        audit = audit_bm25_parity(metadata, bm25_index)

        self.assertEqual(audit["bm25_entry_count_mismatch"], 0)
        self.assertEqual(audit["bm25_chunk_id_set_mismatch"], 0)
        self.assertEqual(audit["bm25_metadata_field_mismatches"], 0)
        self.assertEqual(audit["bm25_filter_policy_count"], 16)
        self.assertEqual(audit["bm25_filter_parity_mismatches"], 0)

    def test_override_freeze_is_content_addressed_and_reproducible(self) -> None:
        rng = np.random.default_rng(11)
        embeddings = rng.normal(size=(3599, 4)).astype(np.float32)
        embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
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
            "row_count": 3599,
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
                "built_at": "2026-07-18T03:00:00+09:00",
                "chunks_path": DEFAULT_CHUNKS,
                "chunk_manifest_path": DEFAULT_CHUNK_MANIFEST,
                "documents_path": DEFAULT_DOCUMENTS,
                "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
                "index_dir": root / "indexes",
                "report_dir": root / "reports",
                "embeddings_override": embeddings,
                "model_info_override": model_info,
                "token_measurement_override": token_measurement,
            }

            first = build_dense_full_artifacts(**kwargs)
            second = build_dense_full_artifacts(**kwargs)

            self.assertEqual(first, second)
            self.assertEqual(first["dense_artifact_decision"], "GO")
            self.assertEqual(first["hybrid_promotion_decision"], "NOT_MEASURED")
            self.assertEqual(
                file_sha256(Path(first["embedding_path"])), first["embedding_sha256"]
            )
            self.assertEqual(
                file_sha256(Path(first["manifest_path"])), first["manifest_sha256"]
            )
            self.assertEqual(
                file_sha256(Path(first["report_json_path"])), first["report_sha256"]
            )


class FrozenDenseFullArtifactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = sorted(read_jsonl(DEFAULT_CHUNKS), key=lambda row: row["chunk_id"])
        cls.metadata = read_jsonl(FROZEN_METADATA)
        cls.manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        cls.report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        cls.embeddings = np.fromfile(FROZEN_EMBEDDINGS, dtype="<f4").reshape(
            3599, 1024
        )

    def test_actual_dense_full_artifacts_pass_hash_alignment_and_numeric_gates(self) -> None:
        for path in (
            FROZEN_METADATA,
            FROZEN_EMBEDDINGS,
            FROZEN_MANIFEST,
            FROZEN_REPORT,
        ):
            self.assertEqual(file_sha256(path), path.stem.rsplit("_", 1)[1])
        self.assertEqual(len(self.metadata), 3599)
        self.assertEqual(self.embeddings.shape, (3599, 1024))
        self.assertTrue(np.isfinite(self.embeddings).all())
        norms = np.linalg.norm(self.embeddings, axis=1)
        self.assertTrue(np.all(np.abs(norms - 1.0) <= 1e-5))
        self.assertEqual(
            [row["chunk_id"] for row in self.metadata],
            [row["chunk_id"] for row in self.chunks],
        )
        self.assertEqual(
            [row["ordinal"] for row in self.metadata], list(range(3599))
        )
        self.assertTrue(
            all(value is True or value == 0 for value in self.report["gates"].values())
        )
        self.assertEqual(self.report["dense_artifact_decision"], "GO")
        self.assertEqual(self.report["hybrid_promotion_decision"], "NOT_MEASURED")
        self.assertFalse(self.report["retrieval_quality_measured"])
        self.assertEqual(self.report["model"]["embedding_dimension"], 1024)
        self.assertEqual(self.report["model"]["max_sequence_length"], 2048)
        self.assertLessEqual(
            self.report["model"]["repeat_encode_max_abs_diff"], 1e-6
        )
        self.assertEqual(self.report["token_measurement"]["over_requested_max"], 0)
        self.assertEqual(self.report["audit"]["bm25_filter_policy_count"], 16)
        self.assertEqual(self.report["audit"]["bm25_filter_parity_mismatches"], 0)
        self.assertEqual(
            self.manifest["embeddings"]["sha256"], file_sha256(FROZEN_EMBEDDINGS)
        )

    def test_actual_dense_full_refreeze_is_reproducible_without_model_reload(self) -> None:
        kwargs = {
            "built_at": BUILT_AT,
            "chunks_path": DEFAULT_CHUNKS,
            "chunk_manifest_path": DEFAULT_CHUNK_MANIFEST,
            "documents_path": DEFAULT_DOCUMENTS,
            "bm25_manifest_path": DEFAULT_BM25_MANIFEST,
            "index_dir": Path("data/v3/indexes"),
            "report_dir": Path("reports/v3"),
            "embeddings_override": self.embeddings,
            "model_info_override": self.report["model"],
            "token_measurement_override": self.report["token_measurement"],
        }

        first = build_dense_full_artifacts(**kwargs)
        second = build_dense_full_artifacts(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["metadata_sha256"], file_sha256(FROZEN_METADATA))
        self.assertEqual(first["embedding_sha256"], file_sha256(FROZEN_EMBEDDINGS))
        self.assertEqual(first["manifest_sha256"], file_sha256(FROZEN_MANIFEST))
        self.assertEqual(first["report_sha256"], file_sha256(FROZEN_REPORT))


if __name__ == "__main__":
    unittest.main()
