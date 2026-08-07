from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable
from src.v3 import evaluate_requirement_surface_query_canary as evaluator


WRAPPER_VERSION = "requirement-surface-query-canary-replacement-run-v1.0.0"
ABORT_REASON = "aborted_before_first_question_missing_openai_env"
EXPECTED_REVIEWED_SHA256 = (
    "533a4b031369cdd63872cd4f52a33d9128fbcf6cf42a344e2693b4959a76c561"
)
EXPECTED_EVALUATOR_SHA256 = (
    "9515a48970a94a1b5efeb2a6146b98e75396b852fa932324f1e6523acce75d6e"
)
SUPERSEDED_AUTHORIZATION_SHA256 = (
    "4285b6413f0ca8f2fc4f0ff2e8fa8b4a945887f8beac8e1eb948282212a1bcae"
)
SUPERSEDED_STARTED_LEDGER_SHA256 = (
    "8506e75a0cf90ae463a47bfbae564aa335580223e95b41143c6d2ee3a0219076"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_json(url: str, *, api_key: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Preflight endpoint returned HTTP {response.status}: {url}")
        return json.loads(response.read().decode("utf-8"))


def validate_ollama_environment(planner_model: str) -> dict[str, Any]:
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL must be set before authorization consumption")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set before authorization consumption")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("OPENAI_BASE_URL is not a valid HTTP URL")
    if parsed.path.rstrip("/") != "/v1":
        raise RuntimeError("OPENAI_BASE_URL must point to the Ollama /v1 endpoint")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    tags = _get_json(f"{origin}/api/tags")
    models = _get_json(f"{base_url}/models", api_key=api_key)
    ollama_names = sorted(str(row.get("name") or "") for row in tags.get("models", []))
    openai_ids = sorted(str(row.get("id") or "") for row in models.get("data", []))
    if planner_model not in ollama_names and f"{planner_model}:latest" not in ollama_names:
        raise RuntimeError(f"Planner model is absent from Ollama: {planner_model}")
    if planner_model not in openai_ids and f"{planner_model}:latest" not in openai_ids:
        raise RuntimeError(f"Planner model is absent from Ollama OpenAI endpoint: {planner_model}")
    return {
        "openai_base_url": base_url,
        "openai_api_key_present": True,
        "ollama_tags_reachable": True,
        "openai_models_reachable": True,
        "planner_model_present": True,
        "planner_model_tag": planner_model,
        "secret_values_recorded": False,
    }


def preload_runtime(root: Path, planner_model: str) -> tuple[evaluator.LivePairRunner, dict[str, Any]]:
    runner = evaluator.LivePairRunner(root=root, planner_model=planner_model)
    embedding = runner.demo._encode("DNF requirement surface query preflight")
    if not len(embedding) or not all(math.isfinite(float(value)) for value in embedding):
        raise RuntimeError("Embedding model preflight returned invalid values")
    scores = runner.demo._score_pairs(
        [("requirement surface query preflight", "requirement surface query preflight")]
    )
    if len(scores) != 1 or not math.isfinite(float(scores[0])):
        raise RuntimeError("Reranker preflight returned invalid values")
    planned, planner_log = runner.demo._plan("공식 문서에 적힌 이용 조건은 무엇인가요?")
    if not planned:
        raise RuntimeError("Planner preflight returned no requirements")
    return runner, {
        "runtime_initialized": True,
        "bm25_and_dense_indexes_loaded": True,
        "embedding_probe_dimension": len(embedding),
        "reranker_probe_count": len(scores),
        "planner_probe_requirement_count": len(planned),
        "planner_probe_call_succeeded": bool(planner_log),
        "canary_question_or_gold_used": False,
    }


def validate_frozen_lineage(
    *,
    root: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    superseded_authorization_path: Path,
    planner_model: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if file_sha256(reviewed_path) != EXPECTED_REVIEWED_SHA256:
        raise RuntimeError("Reviewed packet SHA changed")
    if file_sha256(Path(evaluator.__file__).resolve()) != EXPECTED_EVALUATOR_SHA256:
        raise RuntimeError("Evaluator SHA changed")
    if file_sha256(superseded_authorization_path) != SUPERSEDED_AUTHORIZATION_SHA256:
        raise RuntimeError("Superseded authorization SHA changed")
    rows = read_jsonl(reviewed_path)
    reviewed_manifest = _load_json(reviewed_manifest_path)
    evaluator.validate_reviewed_export(
        rows, reviewed_manifest, reviewed_sha256=EXPECTED_REVIEWED_SHA256
    )
    superseded = _load_json(superseded_authorization_path)
    current_provenance = evaluator._runtime_provenance(root, planner_model)
    if superseded.get("runtime_provenance") != current_provenance:
        raise RuntimeError("Evaluator/model/index/frozen provenance changed")
    return rows, reviewed_manifest, current_provenance


def close_superseded_run(
    *, root: Path, superseded_authorization_path: Path, started_ledger_path: Path
) -> dict[str, Any]:
    if file_sha256(started_ledger_path) != SUPERSEDED_STARTED_LEDGER_SHA256:
        raise RuntimeError("Superseded start ledger SHA changed")
    for path in (root / "data/v3/evaluation").glob(
        "requirement_surface_query_canary_execution_ledger_*.json"
    ):
        row = _load_json(path)
        if row.get("authorization_sha256") == SUPERSEDED_AUTHORIZATION_SHA256:
            if row.get("status") != "ABORTED_NO_RESULTS":
                raise RuntimeError("Superseded run already has a conflicting completion ledger")
            return {"path": str(path), "sha256": file_sha256(path), "ledger": row}
    ledger = {
        "ledger_schema_version": evaluator.LEDGER_SCHEMA_VERSION,
        "status": "ABORTED_NO_RESULTS",
        "completed_at": _utc_now(),
        "authorization_sha256": SUPERSEDED_AUTHORIZATION_SHA256,
        "authorization_path": superseded_authorization_path.relative_to(root).as_posix(),
        "started_ledger": {
            "path": started_ledger_path.relative_to(root).as_posix(),
            "sha256": SUPERSEDED_STARTED_LEDGER_SHA256,
        },
        "reason": ABORT_REASON,
        "scored_at_abort": "0/32",
        "scored_case_count": 0,
        "results_observed": False,
        "result_artifacts_created": False,
        "input_hashes_unchanged": True,
        "runtime_or_canonical_promoted": False,
    }
    payload = _canonical_json_bytes(ledger)
    sha = _sha256_bytes(payload)
    path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_execution_ledger_{sha}.json"
    )
    write_immutable(path, payload)
    return {"path": str(path), "sha256": sha, "ledger": ledger}


def create_replacement_authorization(
    *,
    root: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    superseded_authorization_path: Path,
    aborted_ledger: dict[str, Any],
    approved_by: str,
    runtime_provenance: dict[str, Any],
    environment_preflight: dict[str, Any],
    runtime_preflight: dict[str, Any],
) -> dict[str, Any]:
    authorization = {
        "authorization_schema_version": evaluator.AUTHORIZATION_SCHEMA_VERSION,
        "status": "authorized_for_exactly_one_canary_run",
        "authorized_at": _utc_now(),
        "authorized_by": approved_by,
        "allowed_run_count": 1,
        "reviewed_packet": {
            "path": reviewed_path.relative_to(root).as_posix(),
            "sha256": file_sha256(reviewed_path),
        },
        "reviewed_manifest": {
            "path": reviewed_manifest_path.relative_to(root).as_posix(),
            "sha256": file_sha256(reviewed_manifest_path),
        },
        "runtime_provenance": runtime_provenance,
        "constraints": {
            "off_on_same_process": True,
            "gold_available_to_decision": False,
            "case_specific_literals_allowed": False,
            "automatic_runtime_or_canonical_promotion": False,
            "training_allowed": False,
        },
        "supersedes": {
            "authorization_sha256": SUPERSEDED_AUTHORIZATION_SHA256,
            "authorization_path": superseded_authorization_path.relative_to(root).as_posix(),
            "aborted_ledger_sha256": aborted_ledger["sha256"],
        },
        "reason": ABORT_REASON,
        "scored_at_abort": "0/32",
        "results_observed": False,
        "preflight_before_authorization_consumption": {
            "passed": True,
            "checked_at": _utc_now(),
            "environment": environment_preflight,
            "runtime": runtime_preflight,
            "wrapper_version": WRAPPER_VERSION,
            "wrapper_source_sha256": file_sha256(Path(__file__).resolve()),
        },
    }
    payload = _canonical_json_bytes(authorization)
    sha = _sha256_bytes(payload)
    path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_run_authorization_{sha}.json"
    )
    write_immutable(path, payload)
    return {"path": str(path), "sha256": sha, "authorization": authorization}


class CountingRunner:
    def __init__(self, runner: evaluator.LivePairRunner) -> None:
        self.runner = runner
        self.attempted = 0
        self.completed = 0

    def run_pair(self, decision_input: dict[str, str]) -> dict[str, Any]:
        self.attempted += 1
        result = self.runner.run_pair(decision_input)
        self.completed += 1
        return result


def run_replacement(
    *,
    root: Path,
    reviewed_path: Path,
    reviewed_manifest_path: Path,
    superseded_authorization_path: Path,
    started_ledger_path: Path,
    approved_by: str,
    planner_model: str,
) -> dict[str, Any]:
    root = root.resolve()
    reviewed_path = reviewed_path.resolve()
    reviewed_manifest_path = reviewed_manifest_path.resolve()
    superseded_authorization_path = superseded_authorization_path.resolve()
    started_ledger_path = started_ledger_path.resolve()

    environment_preflight = validate_ollama_environment(planner_model)
    _, _, provenance = validate_frozen_lineage(
        root=root,
        reviewed_path=reviewed_path,
        reviewed_manifest_path=reviewed_manifest_path,
        superseded_authorization_path=superseded_authorization_path,
        planner_model=planner_model,
    )
    preloaded_runner, runtime_preflight = preload_runtime(root, planner_model)
    aborted = close_superseded_run(
        root=root,
        superseded_authorization_path=superseded_authorization_path,
        started_ledger_path=started_ledger_path,
    )
    replacement = create_replacement_authorization(
        root=root,
        reviewed_path=reviewed_path,
        reviewed_manifest_path=reviewed_manifest_path,
        superseded_authorization_path=superseded_authorization_path,
        aborted_ledger=aborted,
        approved_by=approved_by,
        runtime_provenance=provenance,
        environment_preflight=environment_preflight,
        runtime_preflight=runtime_preflight,
    )
    counting = CountingRunner(preloaded_runner)
    try:
        result = evaluator.execute_once(
            root=root,
            reviewed_path=reviewed_path,
            reviewed_manifest_path=reviewed_manifest_path,
            authorization_path=Path(replacement["path"]),
            planner_model=planner_model,
            runner=counting,
        )
    except Exception as exc:
        failure = {
            "ledger_schema_version": evaluator.LEDGER_SCHEMA_VERSION,
            "status": "FAILED_AUTHORIZATION_CONSUMED",
            "completed_at": _utc_now(),
            "authorization_sha256": replacement["sha256"],
            "reason": type(exc).__name__,
            "error": str(exc),
            "attempted_case_count": counting.attempted,
            "completed_case_count": counting.completed,
            "results_observed": False,
            "runtime_or_canonical_promoted": False,
        }
        payload = _canonical_json_bytes(failure)
        sha = _sha256_bytes(payload)
        path = root / "data/v3/evaluation" / (
            f"requirement_surface_query_canary_execution_ledger_{sha}.json"
        )
        write_immutable(path, payload)
        raise RuntimeError(f"Replacement run failed; failure ledger: {path}") from exc
    return {
        "superseded_aborted_ledger": aborted,
        "replacement_authorization": {
            "path": replacement["path"],
            "sha256": replacement["sha256"],
        },
        "execution": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--reviewed-manifest", type=Path, required=True)
    parser.add_argument("--superseded-authorization", type=Path, required=True)
    parser.add_argument("--started-ledger", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--planner-model", default="qwen3:8b")
    args = parser.parse_args()
    root = args.root.resolve()

    def absolute(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    result = run_replacement(
        root=root,
        reviewed_path=absolute(args.reviewed),
        reviewed_manifest_path=absolute(args.reviewed_manifest),
        superseded_authorization_path=absolute(args.superseded_authorization),
        started_ledger_path=absolute(args.started_ledger),
        approved_by=args.approved_by,
        planner_model=args.planner_model,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
