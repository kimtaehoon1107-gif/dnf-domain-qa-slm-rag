from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import transformers
from transformers import AutoModelForSequenceClassification, AutoTokenizer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


SCORER_VERSION = "entailment-control-scorer-v3.1.0"
SCORE_SCHEMA_VERSION = "entailment-control-score-v3.1"
MANIFEST_SCHEMA_VERSION = "entailment-control-score-manifest-v3.1"
LATENCY_SCHEMA_VERSION = "entailment-control-latency-v3.1"
MAX_LENGTH = 512
BATCH_SIZE = 8
SCORE_DECIMALS = 8

DEFAULT_CASES = Path(
    "data/v3/evidence/"
    "entailment_control_cases_4d7d0343529edb97a3d678d9e4f71752626bb8c28e26af8f77a51a03e5dc949a.jsonl"
)
DEFAULT_CASE_MANIFEST = Path(
    "data/v3/evidence/"
    "entailment_control_manifest_1cab8d50cffc17caefa83614018c637fb617156af3be8d8e898c39083c4800d0.json"
)
DEFAULT_SCORER_SOURCE = Path("src/v3/score_entailment_pilot.py")

MODEL_SPECS = (
    {
        "key": "mdeberta_v3_mnli_xnli",
        "name": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        "revision": "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c",
        "cache_dir_name": "mdeberta_v3_base_mnli_xnli_8adb042",
    },
    {
        "key": "klue_roberta_base_nli",
        "name": "Huffon/klue-roberta-base-nli",
        "revision": "3778d23ecb30a63babb17f5efb37b1493b08d975",
        "cache_dir_name": "klue_roberta_base_nli_3778d23",
    },
)

NLI_TO_VERIFIER = {
    "entailment": "support",
    "neutral": "insufficient",
    "contradiction": "contradiction",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def normalize_id2label(id2label: dict[int | str, str]) -> dict[int, str]:
    normalized = {int(index): label.lower() for index, label in id2label.items()}
    if set(normalized.values()) != set(NLI_TO_VERIFIER):
        raise RuntimeError(f"Unsupported NLI labels: {normalized}")
    return normalized


def prepare_pairs(cases: list[dict[str, Any]]) -> list[tuple[str, str]]:
    ordinals = [row["case_ordinal"] for row in cases]
    if ordinals != list(range(len(cases))):
        raise RuntimeError("Entailment case ordinals are not contiguous")
    if len({row["case_id"] for row in cases}) != len(cases):
        raise RuntimeError("Duplicate entailment case_id")
    return [(row["evidence_text"], row["claim_text"]) for row in cases]


def predictions_from_probabilities(
    probabilities: list[list[float]], id2label: dict[int | str, str]
) -> list[dict[str, Any]]:
    labels = normalize_id2label(id2label)
    output = []
    for values in probabilities:
        if len(values) != len(labels):
            raise RuntimeError("NLI probability width differs from model labels")
        predicted_index = max(range(len(values)), key=lambda index: values[index])
        nli_label = labels[predicted_index]
        output.append(
            {
                "predicted_label": NLI_TO_VERIFIER[nli_label],
                "predicted_nli_label": nli_label,
                "probabilities": {
                    NLI_TO_VERIFIER[labels[index]]: round(
                        float(values[index]), SCORE_DECIMALS
                    )
                    for index in sorted(labels)
                },
            }
        )
    return output


def run_model(
    pairs: list[tuple[str, str]],
    model_spec: dict[str, str],
    model_dir: Path,
    *,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not model_dir.is_dir():
        raise RuntimeError(f"Local model snapshot is missing: {model_dir}")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    measured_at = datetime.now(timezone.utc).isoformat()
    load_start = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir, local_files_only=True, use_fast=False
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir, local_files_only=True
    )
    labels = normalize_id2label(model.config.id2label)
    model.to(device)
    if device == "cuda":
        model.half()
    model.eval()
    load_seconds = time.perf_counter() - load_start

    inference_start = time.perf_counter()
    probability_rows: list[list[float]] = []
    with torch.inference_mode():
        for offset in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[offset : offset + BATCH_SIZE]
            encoded = tokenizer(
                [pair[0] for pair in batch],
                [pair[1] for pair in batch],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            # KLUE-RoBERTa has type_vocab_size=1, while its legacy BertTokenizer
            # emits segment ID 1 for the hypothesis. Pair separators retain the
            # boundary, so token_type_ids must not be passed to this RoBERTa.
            encoded.pop("token_type_ids", None)
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits.float()
            probability_rows.extend(torch.softmax(logits, dim=-1).cpu().tolist())
    if device == "cuda":
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - inference_start
    predictions = predictions_from_probabilities(probability_rows, labels)
    latency = {
        "model_key": model_spec["key"],
        "measured_at": measured_at,
        "device": device,
        "device_name": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "pair_count": len(pairs),
        "batch_size": BATCH_SIZE,
        "max_length": MAX_LENGTH,
        "model_load_seconds": round(load_seconds, 6),
        "inference_seconds": round(inference_seconds, 6),
        "pairs_per_second": round(len(pairs) / inference_seconds, 6),
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated())
        if device == "cuda"
        else None,
    }
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return predictions, latency


def attach_predictions(
    cases: list[dict[str, Any]], predictions: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    expected_count = len(cases)
    if any(len(rows) != expected_count for rows in predictions.values()):
        raise RuntimeError("NLI predictions are missing or misaligned")
    return [
        {
            "score_schema_version": SCORE_SCHEMA_VERSION,
            "case_ordinal": case["case_ordinal"],
            "case_id": case["case_id"],
            "source_id": case["source_id"],
            "gold_label": case["label"],
            "model_predictions": {
                model_key: model_rows[case["case_ordinal"]]
                for model_key, model_rows in sorted(predictions.items())
            },
            "training_allowed": False,
            "final_benchmark_eligible": False,
        }
        for case in cases
    ]


def _model_file_hashes(model_dir: Path) -> dict[str, str]:
    return {
        path.name: file_sha256(path)
        for path in sorted(model_dir.iterdir(), key=lambda item: item.name)
        if path.is_file()
    }


def freeze_outputs(
    root: Path,
    rows: list[dict[str, Any]],
    latencies: list[dict[str, Any]],
    input_paths: dict[str, Path],
    model_metadata: list[dict[str, Any]],
    *,
    device: str,
) -> dict[str, Any]:
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    evidence_dir = root / "data/v3/evidence"
    reports_dir = root / "reports/v3"
    score_bytes = _serialize_jsonl(rows, lambda row: row["case_ordinal"])
    score_sha = _sha256_bytes(score_bytes)
    score_path = evidence_dir / f"entailment_control_scores_{score_sha}.jsonl"
    write_immutable(score_path, score_bytes)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "models": model_metadata,
        "libraries": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "scoring_contract": {
            "premise": "evidence_text",
            "hypothesis": "claim_text",
            "nli_mapping": NLI_TO_VERIFIER,
            "max_length": MAX_LENGTH,
            "batch_size": BATCH_SIZE,
            "device": device,
            "score_rounding_decimals": SCORE_DECIMALS,
            "gold_labels_available_to_model": False,
            "token_type_ids_passed": False,
        },
        "scores": {
            "path": _relative(root, score_path),
            "sha256": score_sha,
            "row_count": len(rows),
            "model_count": len(model_metadata),
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = evidence_dir / f"entailment_control_score_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    latency_report = {
        "latency_schema_version": LATENCY_SCHEMA_VERSION,
        "scores_path": _relative(root, score_path),
        "scores_sha256": score_sha,
        "manifest_path": _relative(root, manifest_path),
        "manifest_sha256": manifest_sha,
        "models": latencies,
        "observational_not_reproducibility_input": True,
    }
    latency_bytes = _canonical_json_bytes(latency_report)
    latency_sha = _sha256_bytes(latency_bytes)
    latency_path = reports_dir / f"entailment_control_latency_{latency_sha}.json"
    write_immutable(latency_path, latency_bytes)
    return {
        "scores_path": str(score_path),
        "scores_sha256": score_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "latency_path": str(latency_path),
        "latency_sha256": latency_sha,
        "latencies": latencies,
    }


def build_and_freeze(
    root: Path,
    cases_path: Path,
    case_manifest_path: Path,
    scorer_source_path: Path,
    model_cache_root: Path,
    *,
    device: str,
) -> dict[str, Any]:
    cases = read_jsonl(cases_path)
    pairs = prepare_pairs(cases)
    predictions = {}
    latencies = []
    metadata = []
    for spec in MODEL_SPECS:
        model_dir = model_cache_root / spec["cache_dir_name"]
        model_predictions, latency = run_model(
            pairs, spec, model_dir, device=device
        )
        predictions[spec["key"]] = model_predictions
        latencies.append(latency)
        metadata.append(
            {
                "key": spec["key"],
                "name": spec["name"],
                "revision": spec["revision"],
                "files": _model_file_hashes(model_dir),
            }
        )
    rows = attach_predictions(cases, predictions)
    return freeze_outputs(
        root,
        rows,
        latencies,
        {
            "cases": cases_path,
            "case_manifest": case_manifest_path,
            "scorer_source": scorer_source_path,
        },
        metadata,
        device=device,
    )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Score v3 controlled NLI cases")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--cases", type=Path, default=root / DEFAULT_CASES)
    parser.add_argument(
        "--case-manifest", type=Path, default=root / DEFAULT_CASE_MANIFEST
    )
    parser.add_argument(
        "--scorer-source", type=Path, default=root / DEFAULT_SCORER_SOURCE
    )
    parser.add_argument(
        "--model-cache-root",
        type=Path,
        default=Path.home() / ".cache/dnf_v3_models",
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_and_freeze(
        args.root.resolve(),
        args.cases.resolve(),
        args.case_manifest.resolve(),
        args.scorer_source.resolve(),
        args.model_cache_root.resolve(),
        device=args.device,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
