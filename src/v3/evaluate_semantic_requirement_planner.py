from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    write_immutable,
)


EVALUATOR_VERSION = "semantic-requirement-planner-eval-v3.0"
GOLD_SCHEMA_VERSION = "semantic-requirement-gold-overlay-v3.0"
PLANNER_SCHEMA_VERSION = "semantic-requirement-planner-output-v3.0"
MATCH_SCHEMA_VERSION = "semantic-requirement-match-v3.0"
REPORT_SCHEMA_VERSION = "semantic-requirement-planner-report-v3.0"
MANIFEST_SCHEMA_VERSION = "semantic-requirement-planner-manifest-v3.0"

DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CEILING = Path(
    "data/v3/evaluation/claim_ceiling_inputs_"
    "c8127eee3283dd5808a62bd846b480c44b9672e5f28d88ca47ab301818c82215.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/semantic_requirement_planner_contract.md")

DEFAULT_GOLD_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_PLANNER_MODEL = "qwen3:8b"
DEFAULT_MATCHER_MODEL = "qwen3:4b"

RECALL_GATE = 0.90
PRECISION_GATE = 0.85
OVER_ENUMERATION_GATE = 0.10
ALL_RECALLED_GATE = 0.85


class GoldRequirementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=160)
    relation: str = Field(min_length=1, max_length=160)
    value_type: str = Field(min_length=1, max_length=80)
    subject_group: str = Field(min_length=1, max_length=120)
    answerable_from_docs: bool
    acceptable_evidence_group_ids: list[str] = Field(max_length=8)
    qualifiers: list[str] = Field(max_length=8)
    time_scope: str | None = Field(default=None, max_length=100)
    coordination_scope: str | None = Field(default=None, max_length=100)


class GoldCaseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    requirements: list[GoldRequirementDraft] = Field(min_length=1, max_length=8)


class GoldBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[GoldCaseDraft] = Field(min_length=1, max_length=8)


class PlannerRequirementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=160)
    relation: str = Field(min_length=1, max_length=160)
    value_type: str = Field(min_length=1, max_length=80)
    subject_group: str = Field(min_length=1, max_length=120)
    answerable_from_docs: bool
    qualifiers: list[str] = Field(max_length=8)
    time_scope: str | None = Field(default=None, max_length=100)
    coordination_scope: str | None = Field(default=None, max_length=100)


class PlannerCaseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    requirements: list[PlannerRequirementDraft] = Field(min_length=1, max_length=8)


class PlannerBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[PlannerCaseDraft] = Field(min_length=1, max_length=8)


class PairJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_index: int = Field(ge=1, le=8)
    gold_index: int = Field(ge=1, le=8)
    verdict: Literal["MATCH", "PARTIAL_MATCH", "NO_MATCH", "AMBIGUOUS"]
    rationale: str = Field(min_length=1, max_length=400)


class MatcherCaseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    pair_judgments: list[PairJudgment] = Field(min_length=1, max_length=64)


class MatcherBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[MatcherCaseDraft] = Field(min_length=1, max_length=8)


GOLD_SYSTEM_PROMPT = """You are Gold Author B for an evaluation overlay.
Derive atomic answer requirements from the QUESTION. The question is authoritative.
Evidence-group hints may only resolve ambiguity and map support; never add a field
merely because it appears in evidence. One requirement is one requested fact.
Split coordinated facts. Preserve which subject each fact belongs to through
subject_group. subject is the entity being asked about; relation is the requested
attribute or relation, never the literal string subject_group. value_type describes
the expected answer form, such as amount, date, duration, boolean, condition, place,
or text. Official stable game rules and published facts are answerable_from_docs=true.
Use false only when the requested value necessarily depends on private user state,
live external state, prediction, or a non-document source. Keep qualifiers short and
only when material; do not copy evidence sentences into qualifiers. Leave optional
scopes null unless the question explicitly needs them.
Atomic example: "What are product X's cost and expiry?" becomes two requirements,
X-cost-amount and X-expiry-date, both in subject_group X. Return only structured JSON."""

PLANNER_SYSTEM_PROMPT = """You are Planner A. Read only each QUESTION and enumerate
the atomic facts an adequate answer must provide. One requirement is one requested
fact; split coordinated fields and preserve subject attribution with subject_group.
Use concise semantic relation names, not copied question prose. value_type describes
the expected answer form, such as amount, date, duration, boolean, condition, place,
or text. Official stable game rules and published facts are answerable_from_docs=true.
Use false only when the requested value necessarily depends on private user state,
live external state, prediction, or a non-document source. Keep qualifiers short and
only when material; leave optional scopes null unless explicitly needed.
Atomic example: "What are product X's cost and expiry?" becomes two requirements,
X-cost-amount and X-expiry-date, both in subject_group X.
Do not retrieve, cite, answer, or invent evidence. Return only structured JSON."""

MATCHER_SYSTEM_PROMPT = """You are Matcher C, an independent semantic evaluator.
Judge every prediction/gold pair as MATCH, PARTIAL_MATCH, NO_MATCH, or AMBIGUOUS.
MATCH requires the same subject, semantically identical relation, compatible value
type, preserved subject_group attribution, no missing material qualifier, and
compatible answerable_from_docs. A broad or bundled prediction cannot fully match
multiple atomic gold requirements. Return one judgment for every Cartesian pair.
All fields are free-text semantic labels: wording, language, identifier style, and
granularity need not be identical. subject_group is correct when the fact is attached
to the same real-world entity, even if its label differs. A more general compatible
value type can match a narrower one. Lexical overlap alone is never sufficient.
Return only structured JSON."""


T = TypeVar("T", bound=BaseModel)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _fixed_prompt_hash(prompt: str) -> str:
    return _sha256_bytes(prompt.encode("utf-8"))


def _case_id(row: dict[str, Any]) -> str:
    return str(row.get("dev_id") or row.get("case_id"))


def build_population(
    canary_rows: list[dict[str, Any]],
    dev_rows: list[dict[str, Any]],
    ceiling_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ceiling_ids = {_case_id(row) for row in ceiling_rows}
    combined: list[tuple[str, dict[str, Any]]] = [
        *(("downgraded_canary_32", row) for row in canary_rows),
        *(("adaptive_dev_63", row) for row in dev_rows),
    ]
    output = []
    seen = set()
    for dataset, row in combined:
        case_id = _case_id(row)
        if not case_id or case_id == "None":
            raise RuntimeError("Evaluation row has no case identifier")
        if case_id in seen:
            raise RuntimeError(f"Duplicate primary case id: {case_id}")
        seen.add(case_id)
        groups = [
            {
                "group_id": group["group_id"],
                "evidence_span": group.get("evidence_span", ""),
            }
            for group in row.get("evidence_groups", [])
        ]
        output.append(
            {
                "case_id": case_id,
                "dataset": dataset,
                "question": row["question"],
                "answerability_label": row.get("answerability"),
                "source_ids": sorted(set(row.get("source_ids", []))),
                "time_scope": row.get("time_scope"),
                "query_kind": row.get("query_kind"),
                "evidence_group_hints": groups,
                "claim_ceiling_stress_slice": case_id in ceiling_ids,
            }
        )
    if len(output) != 95:
        raise RuntimeError(f"Expected 95 unique primary cases, got {len(output)}")
    if not ceiling_ids.issubset(seen) or len(ceiling_ids) != 15:
        raise RuntimeError("Claim-ceiling 15 must be an exact subset of primary rows")
    return sorted(output, key=lambda row: row["case_id"])


def gold_prompt(batch: list[dict[str, Any]]) -> str:
    payload = [
        {
            "case_id": f"case_{index}",
            "question": row["question"],
            "evidence_group_hints": row["evidence_group_hints"],
        }
        for index, row in enumerate(batch, 1)
    ]
    return "Author the frozen gold overlay for these cases:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def planner_prompt(batch: list[dict[str, Any]]) -> str:
    payload = [
        {"case_id": f"case_{index}", "question": row["question"]}
        for index, row in enumerate(batch, 1)
    ]
    return "Plan requirements for these cases:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def matcher_prompt(
    gold_batch: list[dict[str, Any]], planner_by_id: dict[str, dict[str, Any]]
) -> str:
    payload = []
    for index, gold in enumerate(gold_batch, 1):
        case_id = gold["case_id"]
        payload.append(
            {
                "case_id": f"case_{index}",
                "gold_requirements": gold["requirements"],
                "predicted_requirements": planner_by_id[case_id]["requirements"],
                "expected_pair_count": len(gold["requirements"])
                * len(planner_by_id[case_id]["requirements"]),
            }
        )
    return "Judge every Cartesian requirement pair for these cases:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def _configured_base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1").rstrip("/")


def _ollama_api_url(base_url: str, path: str) -> str:
    parsed = urlsplit(base_url)
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/v1"):
        base_path = base_path[:-3]
    return urlunsplit((parsed.scheme, parsed.netloc, f"{base_path}{path}", "", ""))


def _json_request(url: str, payload: dict[str, Any] | None, timeout: float) -> Any:
    data = None if payload is None else _canonical_json_bytes(payload)
    request = Request(
        url,
        data=data,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json", "User-Agent": EVALUATOR_VERSION},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def runtime_metadata(model: str, timeout: float) -> dict[str, Any]:
    base_url = _configured_base_url()
    parsed = urlsplit(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("This cycle requires a local Ollama OpenAI-compatible endpoint")
    version = _json_request(_ollama_api_url(base_url, "/api/version"), None, timeout)
    tags = _json_request(_ollama_api_url(base_url, "/api/tags"), None, timeout)
    match = next(
        (
            row
            for row in tags.get("models", [])
            if row.get("name") == model or row.get("model") == model
        ),
        None,
    )
    if match is None:
        raise RuntimeError(f"Ollama model is not installed: {model}")
    return {
        "provider": "ollama_openai_compatible",
        "base_url": base_url,
        "model_tag": model,
        "model_sha256": match.get("digest"),
        "model_details": match.get("details", {}),
        "ollama_version": version.get("version"),
        "temperature": 0,
    }


def call_structured(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    output_type: type[T],
    timeout: float,
) -> tuple[T, dict[str, Any]]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required (use the Ollama dummy key)")
    from openai import OpenAI, __version__ as sdk_version

    started = time.perf_counter()
    if model.startswith("qwen3:"):
        response = _json_request(
            _ollama_api_url(_configured_base_url(), "/api/chat"),
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "think": False,
                "format": output_type.model_json_schema(),
                "options": {"temperature": 0, "num_predict": 5000},
            },
            timeout,
        )
        content = response.get("message", {}).get("content")
        if not content:
            raise RuntimeError(f"Ollama native model returned no content: {model}")
        parsed = output_type.model_validate_json(content)
        return parsed, {
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "returned_model": response.get("model", model),
            "sdk_version": "ollama_native_http",
            "prompt_tokens": int(response.get("prompt_eval_count", 0) or 0),
            "completion_tokens": int(response.get("eval_count", 0) or 0),
        }

    client = OpenAI(max_retries=1, timeout=timeout)
    kwargs: dict[str, Any] = {}
    if model.startswith("qwen3"):
        kwargs["extra_body"] = {"think": False}
    response = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=output_type,
        temperature=0,
        max_tokens=5000,
        **kwargs,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(f"Model returned no structured output: {model}")
    usage = response.usage
    return parsed, {
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "returned_model": response.model,
        "sdk_version": sdk_version,
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def _batched(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _normalize_requirements(
    requirements: list[dict[str, Any]], *, gold: bool
) -> list[dict[str, Any]]:
    output = []
    for index, requirement in enumerate(requirements, 1):
        normalized = dict(requirement)
        normalized["requirement_id"] = f"requirement_{index}"
        if gold:
            normalized["acceptable_evidence_group_ids"] = sorted(
                set(normalized["acceptable_evidence_group_ids"])
            )
        normalized["qualifiers"] = list(normalized.get("qualifiers", []))
        output.append(normalized)
    return output


def author_gold(
    population: list[dict[str, Any]],
    *,
    model: str,
    batch_size: int,
    timeout: float,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    call_logs = []
    for batch in _batched(population, batch_size):
        parsed, call_log = caller(
            model=model,
            system_prompt=GOLD_SYSTEM_PROMPT,
            user_prompt=gold_prompt(batch),
            output_type=GoldBatchOutput,
            timeout=timeout,
        )
        cases = {case.case_id: case.model_dump() for case in parsed.cases}
        expected = {f"case_{index}" for index in range(1, len(batch) + 1)}
        if set(cases) != expected:
            raise RuntimeError("Gold author returned missing or unexpected case ids")
        for index, source in enumerate(batch, 1):
            case = cases[f"case_{index}"]
            allowed_groups = {
                group["group_id"] for group in source["evidence_group_hints"]
            }
            requirements = _normalize_requirements(case["requirements"], gold=True)
            referenced = {
                group_id
                for requirement in requirements
                for group_id in requirement["acceptable_evidence_group_ids"]
            }
            if not referenced.issubset(allowed_groups):
                raise RuntimeError(
                    f"Gold author invented evidence group: {source['case_id']}"
                )
            rows.append(
                {
                    "gold_schema_version": GOLD_SCHEMA_VERSION,
                    "case_id": source["case_id"],
                    "dataset": source["dataset"],
                    "question": source["question"],
                    "source_ids": source["source_ids"],
                    "time_scope": source["time_scope"],
                    "query_kind": source["query_kind"],
                    "claim_ceiling_stress_slice": source[
                        "claim_ceiling_stress_slice"
                    ],
                    "requirements": requirements,
                    "gold_status": "authored_frozen_pending_human_adjudication",
                }
            )
        call_logs.append(call_log)
    return sorted(rows, key=lambda row: row["case_id"]), call_logs


def run_planner(
    population: list[dict[str, Any]],
    *,
    model: str,
    batch_size: int,
    timeout: float,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    call_logs = []
    for batch in _batched(population, batch_size):
        parsed, call_log = caller(
            model=model,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=planner_prompt(batch),
            output_type=PlannerBatchOutput,
            timeout=timeout,
        )
        cases = {case.case_id: case.model_dump() for case in parsed.cases}
        expected = {f"case_{index}" for index in range(1, len(batch) + 1)}
        if set(cases) != expected:
            raise RuntimeError("Planner returned missing or unexpected case ids")
        for index, source in enumerate(batch, 1):
            case = cases[f"case_{index}"]
            rows.append(
                {
                    "planner_schema_version": PLANNER_SCHEMA_VERSION,
                    "case_id": source["case_id"],
                    "requirements": _normalize_requirements(
                        case["requirements"], gold=False
                    ),
                }
            )
        call_logs.append(call_log)
    return sorted(rows, key=lambda row: row["case_id"]), call_logs


def _normalize_pair_matrix(
    case_id: str,
    pair_judgments: list[dict[str, Any]],
    prediction_count: int,
    gold_count: int,
) -> list[dict[str, Any]]:
    actual: dict[tuple[int, int], dict[str, Any]] = {}
    for row in pair_judgments:
        key = (row["prediction_index"], row["gold_index"])
        if key in actual or not (
            1 <= key[0] <= prediction_count and 1 <= key[1] <= gold_count
        ):
            continue
        normalized = dict(row)
        normalized["judgment_origin"] = "model"
        actual[key] = normalized
    expected = {
        (prediction_index, gold_index)
        for prediction_index in range(1, prediction_count + 1)
        for gold_index in range(1, gold_count + 1)
    }
    for key in sorted(expected - set(actual)):
        actual[key] = {
            "prediction_index": key[0],
            "gold_index": key[1],
            "verdict": "NO_MATCH",
            "rationale": "matcher_omitted_pair_defaulted_conservatively_to_no_match",
            "judgment_origin": "conservative_default",
        }
    return [actual[key] for key in sorted(actual)]


def run_matcher(
    gold_rows: list[dict[str, Any]],
    planner_rows: list[dict[str, Any]],
    *,
    model: str,
    batch_size: int,
    timeout: float,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    planner_by_id = {row["case_id"]: row for row in planner_rows}
    rows = []
    call_logs = []
    for batch in _batched(gold_rows, batch_size):
        parsed, call_log = caller(
            model=model,
            system_prompt=MATCHER_SYSTEM_PROMPT,
            user_prompt=matcher_prompt(batch, planner_by_id),
            output_type=MatcherBatchOutput,
            timeout=timeout,
        )
        cases = {case.case_id: case.model_dump() for case in parsed.cases}
        expected = {f"case_{index}" for index in range(1, len(batch) + 1)}
        if set(cases) != expected:
            raise RuntimeError("Matcher returned missing or unexpected case ids")
        for index, gold in enumerate(batch, 1):
            case_id = gold["case_id"]
            pair_judgments = _normalize_pair_matrix(
                case_id,
                cases[f"case_{index}"]["pair_judgments"],
                len(planner_by_id[case_id]["requirements"]),
                len(gold["requirements"]),
            )
            rows.append(
                {
                    "match_schema_version": MATCH_SCHEMA_VERSION,
                    "case_id": case_id,
                    "pair_judgments": sorted(
                        pair_judgments,
                        key=lambda row: (
                            row["prediction_index"],
                            row["gold_index"],
                        ),
                    ),
                }
            )
        call_logs.append(call_log)
    return sorted(rows, key=lambda row: row["case_id"]), call_logs


def maximum_match_edges(pair_judgments: list[dict[str, Any]]) -> list[tuple[int, int]]:
    adjacency: dict[int, list[int]] = {}
    for row in pair_judgments:
        if row["verdict"] == "MATCH":
            adjacency.setdefault(row["prediction_index"], []).append(row["gold_index"])
    gold_to_prediction: dict[int, int] = {}

    def augment(prediction: int, visited: set[int]) -> bool:
        for gold in sorted(adjacency.get(prediction, [])):
            if gold in visited:
                continue
            visited.add(gold)
            if gold not in gold_to_prediction or augment(
                gold_to_prediction[gold], visited
            ):
                gold_to_prediction[gold] = prediction
                return True
        return False

    for prediction in sorted(adjacency):
        augment(prediction, set())
    return sorted((prediction, gold) for gold, prediction in gold_to_prediction.items())


def _fraction(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "rate": round(successes / total, 6) if total else None,
    }


def _score_subset(cases: list[dict[str, Any]]) -> dict[str, Any]:
    gold_total = sum(case["gold_count"] for case in cases)
    prediction_total = sum(case["prediction_count"] for case in cases)
    matched_total = sum(case["matched_count"] for case in cases)
    all_recalled = sum(case["matched_count"] == case["gold_count"] for case in cases)
    over_enumerated = sum(
        case["prediction_count"] > case["matched_count"] for case in cases
    )
    return {
        "question_count": len(cases),
        "micro_recall": _fraction(matched_total, gold_total),
        "micro_precision": _fraction(matched_total, prediction_total),
        "all_requirements_recalled_questions": _fraction(all_recalled, len(cases)),
        "over_enumerated_questions": _fraction(over_enumerated, len(cases)),
        "docs_false_positive_count": sum(case["docs_false_positive"] for case in cases),
        "docs_false_negative_count": sum(case["docs_false_negative"] for case in cases),
        "ambiguous_pair_count": sum(case["ambiguous_pair_count"] for case in cases),
        "partial_pair_count": sum(case["partial_pair_count"] for case in cases),
        "matcher_protocol_omission_count": sum(
            case["matcher_protocol_omission_count"] for case in cases
        ),
    }


def score_cases(
    gold_rows: list[dict[str, Any]],
    planner_rows: list[dict[str, Any]],
    match_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    planner_by_id = {row["case_id"]: row for row in planner_rows}
    match_by_id = {row["case_id"]: row for row in match_rows}
    cases = []
    for gold in gold_rows:
        case_id = gold["case_id"]
        planner = planner_by_id[case_id]
        judgments = match_by_id[case_id]["pair_judgments"]
        edges = maximum_match_edges(judgments)
        docs_fp = 0
        docs_fn = 0
        matched_predictions = set()
        for prediction_index, gold_index in edges:
            matched_predictions.add(prediction_index)
            predicted_docs = planner["requirements"][prediction_index - 1][
                "answerable_from_docs"
            ]
            gold_docs = gold["requirements"][gold_index - 1]["answerable_from_docs"]
            docs_fp += int(predicted_docs and not gold_docs)
            docs_fn += int(gold_docs and not predicted_docs)
        if all(not req["answerable_from_docs"] for req in gold["requirements"]):
            docs_fp += sum(
                requirement["answerable_from_docs"]
                for index, requirement in enumerate(planner["requirements"], 1)
                if index not in matched_predictions
            )
        case = {
            "case_id": case_id,
            "dataset": gold["dataset"],
            "source_ids": gold["source_ids"],
            "time_scope": gold["time_scope"],
            "query_kind": gold["query_kind"],
            "claim_ceiling_stress_slice": gold["claim_ceiling_stress_slice"],
            "gold_count": len(gold["requirements"]),
            "prediction_count": len(planner["requirements"]),
            "matched_count": len(edges),
            "matched_edges": [
                {"prediction_index": prediction, "gold_index": gold_index}
                for prediction, gold_index in edges
            ],
            "docs_false_positive": docs_fp,
            "docs_false_negative": docs_fn,
            "ambiguous_pair_count": sum(
                row["verdict"] == "AMBIGUOUS" for row in judgments
            ),
            "partial_pair_count": sum(
                row["verdict"] == "PARTIAL_MATCH" for row in judgments
            ),
            "matcher_protocol_omission_count": sum(
                row.get("judgment_origin") == "conservative_default"
                for row in judgments
            ),
            "answerable_scope": (
                "docs"
                if all(req["answerable_from_docs"] for req in gold["requirements"])
                else "realtime_personal"
                if all(
                    not req["answerable_from_docs"] for req in gold["requirements"]
                )
                else "mixed"
            ),
        }
        cases.append(case)

    slices: dict[str, Any] = {
        "primary_unique_95": _score_subset(cases),
        "downgraded_canary_32": _score_subset(
            [case for case in cases if case["dataset"] == "downgraded_canary_32"]
        ),
        "adaptive_dev_63": _score_subset(
            [case for case in cases if case["dataset"] == "adaptive_dev_63"]
        ),
        "claim_ceiling_stress_15": _score_subset(
            [case for case in cases if case["claim_ceiling_stress_slice"]]
        ),
        "single_requirement": _score_subset(
            [case for case in cases if case["gold_count"] == 1]
        ),
        "multi_requirement": _score_subset(
            [case for case in cases if case["gold_count"] > 1]
        ),
    }
    sources = sorted({source for case in cases for source in case["source_ids"]})
    slices["by_source"] = {
        source: _score_subset([case for case in cases if source in case["source_ids"]])
        for source in sources
    }
    slices["docs_scope"] = _score_subset(
        [
            case
            for case, gold in zip(cases, gold_rows, strict=True)
            if all(req["answerable_from_docs"] for req in gold["requirements"])
        ]
    )
    slices["realtime_personal_scope"] = _score_subset(
        [
            case
            for case, gold in zip(cases, gold_rows, strict=True)
            if all(not req["answerable_from_docs"] for req in gold["requirements"])
        ]
    )
    slices["mixed_answerable_scope"] = _score_subset(
        [
            case
            for case, gold in zip(cases, gold_rows, strict=True)
            if len({req["answerable_from_docs"] for req in gold["requirements"]}) > 1
        ]
    )
    return cases, slices


def needs_human_review(case: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    if case["gold_count"] > 1:
        reasons.append("multi_requirement_100pct")
    if len(case["source_ids"]) > 1:
        reasons.append("mixed_source_100pct")
    text_flags = " ".join(
        str(case.get(key) or "") for key in ("query_kind", "time_scope")
    ).lower()
    if (
        case.get("answerable_scope") != "docs"
        or case["docs_false_positive"]
        or "realtime" in text_flags
        or "personal" in text_flags
    ):
        reasons.append("realtime_or_personal_100pct")
    if case["ambiguous_pair_count"]:
        reasons.append("ambiguous_100pct")
    if case["partial_pair_count"] or case["matched_count"] != case["gold_count"]:
        reasons.append("matcher_disagreement_100pct")
    if case.get("matcher_protocol_omission_count"):
        reasons.append("matcher_protocol_omission_100pct")
    if not reasons and int(hashlib.sha256(case["case_id"].encode()).hexdigest()[:8], 16) % 5 == 0:
        reasons.append("simple_single_deterministic_20pct_spot")
    return bool(reasons), reasons


def _latency_summary(logs: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["latency_ms"] for row in logs]
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else None
    return {
        "call_count": len(values),
        "median_ms": round(statistics.median(values), 3) if values else None,
        "p95_ms": p95,
        "total_ms": round(sum(values), 3) if values else None,
        "measurement_status": "call_level_measured" if values else "unavailable",
    }


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _markdown(report: dict[str, Any]) -> str:
    primary = report["metrics"]["primary_unique_95"]
    gates = report["gates"]
    lines = [
        "# Semantic Requirement Planner provisional evaluation",
        "",
        f"- Decision: **{report['decision']}**",
        f"- Primary population: {primary['question_count']} unique questions",
        "- Claim-ceiling 15 is a non-additive stress slice of the downgraded 32.",
        "",
        "## Primary metrics",
        "",
        f"- micro recall: {primary['micro_recall']['successes']}/{primary['micro_recall']['total']} ({primary['micro_recall']['rate']})",
        f"- micro precision: {primary['micro_precision']['successes']}/{primary['micro_precision']['total']} ({primary['micro_precision']['rate']})",
        f"- all requirements recalled: {primary['all_requirements_recalled_questions']['successes']}/{primary['all_requirements_recalled_questions']['total']} ({primary['all_requirements_recalled_questions']['rate']})",
        f"- over-enumerated questions: {primary['over_enumerated_questions']['successes']}/{primary['over_enumerated_questions']['total']} ({primary['over_enumerated_questions']['rate']})",
        f"- docs false positives: {primary['docs_false_positive_count']}",
        f"- docs false negatives: {primary['docs_false_negative_count']}",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- {name}: {value}" for name, value in gates.items())
    lines.extend(
        [
            "",
            "## Human adjudication",
            "",
            f"- planned: {report['human_adjudication']['planned_count']}",
            "- completed: 0",
            "- judge-human agreement: pending",
            "- judge false match / false nonmatch: pending",
            "",
            "Automatic matcher metrics are provisional. This report cannot issue a",
            "reranker-pilot GO until the named human review overlay is completed.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_and_freeze(
    root: Path,
    *,
    gold_model: str = DEFAULT_GOLD_MODEL,
    planner_model: str = DEFAULT_PLANNER_MODEL,
    matcher_model: str = DEFAULT_MATCHER_MODEL,
    batch_size: int = 5,
    timeout: float = 180.0,
    evaluated_at: str | None = None,
    frozen_gold_overlay: Path | None = None,
    frozen_gold_manifest: Path | None = None,
    frozen_planner_outputs: Path | None = None,
    frozen_matches: Path | None = None,
    prior_report: Path | None = None,
    gold_stage_wall_ms: float | None = None,
    planner_stage_wall_ms: float | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if len({gold_model, planner_model, matcher_model}) != 3:
        raise RuntimeError("Gold B, Planner A, and Matcher C must use distinct model tags")
    input_paths = {
        "canary_32": root / DEFAULT_CANARY,
        "adaptive_dev_63": root / DEFAULT_DEV,
        "claim_ceiling_15": root / DEFAULT_CEILING,
        "contract": root / DEFAULT_CONTRACT,
        "source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    population = build_population(
        read_jsonl(input_paths["canary_32"]),
        read_jsonl(input_paths["adaptive_dev_63"]),
        read_jsonl(input_paths["claim_ceiling_15"]),
    )
    model_metadata = {
        "gold_author_b": runtime_metadata(gold_model, timeout),
        "planner_a": runtime_metadata(planner_model, timeout),
        "matcher_c": runtime_metadata(matcher_model, timeout),
    }

    resume_requested = any(
        value is not None
        for value in (frozen_gold_overlay, frozen_gold_manifest, frozen_planner_outputs)
    )
    if resume_requested and not all(
        value is not None
        for value in (frozen_gold_overlay, frozen_gold_manifest, frozen_planner_outputs)
    ):
        raise RuntimeError("Resume requires gold overlay, gold manifest, and planner outputs")

    if resume_requested:
        gold_path = (root / frozen_gold_overlay).resolve()  # type: ignore[arg-type]
        gold_manifest_path = (root / frozen_gold_manifest).resolve()  # type: ignore[arg-type]
        planner_path = (root / frozen_planner_outputs).resolve()  # type: ignore[arg-type]
        gold_rows = read_jsonl(gold_path)
        planner_rows = read_jsonl(planner_path)
        expected_ids = {row["case_id"] for row in population}
        if {row["case_id"] for row in gold_rows} != expected_ids:
            raise RuntimeError("Frozen gold overlay does not cover the primary 95")
        if {row["case_id"] for row in planner_rows} != expected_ids:
            raise RuntimeError("Frozen planner output does not cover the primary 95")
        gold_sha = file_sha256(gold_path)
        gold_manifest_sha = file_sha256(gold_manifest_path)
        planner_sha = file_sha256(planner_path)
        gold_logs = []
        planner_logs = []
    else:
        gold_rows, gold_logs = author_gold(
            population, model=gold_model, batch_size=batch_size, timeout=timeout
        )
        gold_bytes = _serialize_jsonl(gold_rows, lambda row: row["case_id"])
        gold_sha = _sha256_bytes(gold_bytes)
        gold_path = root / "data/v3/evaluation" / f"semantic_requirement_gold_overlay_{gold_sha}.jsonl"
        write_immutable(gold_path, gold_bytes)

        gold_manifest = {
            "gold_schema_version": GOLD_SCHEMA_VERSION,
            "gold_author": model_metadata["gold_author_b"],
            "gold_prompt_sha256": _fixed_prompt_hash(GOLD_SYSTEM_PROMPT),
            "frozen_before_planner": True,
            "planner_output_visible_to_gold_author": False,
            "human_status": "pending",
            "inputs": {
                name: {"path": _relative(root, path), "sha256": input_hashes[name]}
                for name, path in input_paths.items()
                if name in {"canary_32", "adaptive_dev_63", "claim_ceiling_15", "contract"}
            },
            "artifact": {"path": _relative(root, gold_path), "sha256": gold_sha, "row_count": len(gold_rows)},
        }
        gold_manifest_bytes = _canonical_json_bytes(gold_manifest)
        gold_manifest_sha = _sha256_bytes(gold_manifest_bytes)
        gold_manifest_path = root / "data/v3/evaluation" / f"semantic_requirement_gold_manifest_{gold_manifest_sha}.json"
        write_immutable(gold_manifest_path, gold_manifest_bytes)

        planner_rows, planner_logs = run_planner(
            population, model=planner_model, batch_size=batch_size, timeout=timeout
        )
        planner_bytes = _serialize_jsonl(planner_rows, lambda row: row["case_id"])
        planner_sha = _sha256_bytes(planner_bytes)
        planner_path = root / "data/v3/evaluation" / f"semantic_requirement_planner_outputs_{planner_sha}.jsonl"
        write_immutable(planner_path, planner_bytes)

    if frozen_matches is not None:
        match_path = (root / frozen_matches).resolve()
        match_rows = read_jsonl(match_path)
        if {row["case_id"] for row in match_rows} != {
            row["case_id"] for row in population
        }:
            raise RuntimeError("Frozen matcher output does not cover the primary 95")
        match_sha = file_sha256(match_path)
        matcher_logs = []
    else:
        match_rows, matcher_logs = run_matcher(
            gold_rows,
            planner_rows,
            model=matcher_model,
            batch_size=batch_size,
            timeout=timeout,
        )
        match_bytes = _serialize_jsonl(match_rows, lambda row: row["case_id"])
        match_sha = _sha256_bytes(match_bytes)
        match_path = root / "data/v3/evaluation" / f"semantic_requirement_matches_{match_sha}.jsonl"
        write_immutable(match_path, match_bytes)

    case_scores, metrics = score_cases(gold_rows, planner_rows, match_rows)
    gold_by_id = {row["case_id"]: row for row in gold_rows}
    planner_by_id = {row["case_id"]: row for row in planner_rows}
    match_by_id = {row["case_id"]: row for row in match_rows}
    review_rows = []
    for case in case_scores:
        selected, reasons = needs_human_review(case)
        if selected:
            case_id = case["case_id"]
            review_rows.append(
                {
                    "review_schema_version": "semantic-requirement-human-review-v3.0",
                    "case_id": case_id,
                    "question": gold_by_id[case_id]["question"],
                    "gold_requirements": gold_by_id[case_id]["requirements"],
                    "planner_requirements": planner_by_id[case_id]["requirements"],
                    "matcher_pair_judgments": match_by_id[case_id]["pair_judgments"],
                    "automatic_matched_edges": case["matched_edges"],
                    "review_reasons": reasons,
                    "human_review": {
                        "gold_overlay_verdict": None,
                        "adjudicated_gold_requirements": None,
                        "adjudicated_match_edges": None,
                        "planner_atomicity_verdict": None,
                        "answerable_from_docs_verdict": None,
                        "rationale": None,
                        "reviewer_id": None,
                        "reviewed_at": None,
                    },
                }
            )
    review_bytes = _serialize_jsonl(review_rows, lambda row: row["case_id"])
    review_sha = _sha256_bytes(review_bytes)
    review_path = root / "outputs/v3" / f"semantic_requirement_human_review_{review_sha}.jsonl"
    write_immutable(review_path, review_bytes)

    primary = metrics["primary_unique_95"]
    gates = {
        "micro_requirement_recall_gte_0_90": primary["micro_recall"]["rate"] >= RECALL_GATE,
        "micro_requirement_precision_gte_0_85": primary["micro_precision"]["rate"] >= PRECISION_GATE,
        "over_enumerated_question_rate_lte_0_10": primary["over_enumerated_questions"]["rate"] <= OVER_ENUMERATION_GATE,
        "docs_false_positive_zero": primary["docs_false_positive_count"] == 0,
        "all_requirements_recalled_rate_gte_0_85": primary["all_requirements_recalled_questions"]["rate"] >= ALL_RECALLED_GATE,
        "human_adjudication_complete": False,
    }
    automatic_gates_pass = all(value for name, value in gates.items() if name != "human_adjudication_complete")
    latency = {
        "gold_author_b": _latency_summary(gold_logs),
        "planner_a": _latency_summary(planner_logs),
        "matcher_c": _latency_summary(matcher_logs),
    }
    if gold_stage_wall_ms is not None:
        latency["gold_author_b"] = {
            "call_count": None,
            "median_ms": None,
            "p95_ms": None,
            "total_ms": gold_stage_wall_ms,
            "measurement_status": "stage_wall_clock_from_process_and_artifact_timestamps",
        }
    if planner_stage_wall_ms is not None:
        latency["planner_a"] = {
            "call_count": None,
            "median_ms": None,
            "p95_ms": None,
            "total_ms": planner_stage_wall_ms,
            "measurement_status": "stage_wall_clock_from_artifact_timestamps",
        }
    prior_report_path = None
    if prior_report is not None:
        prior_report_path = (root / prior_report).resolve()
        prior = json.loads(prior_report_path.read_text(encoding="utf-8"))
        latency["matcher_c"] = dict(prior["latency"]["matcher_c"])
        latency["matcher_c"]["measurement_status"] = "call_level_measured_in_preserved_prior_report"

    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_role": "development_only_semantic_planner_evaluation",
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "decision": "PENDING_HUMAN_ADJUDICATION",
        "automatic_gates_pass": automatic_gates_pass,
        "metrics": metrics,
        "gates": gates,
        "human_adjudication": {
            "reviewer": "kimdh_user",
            "planned_count": len(review_rows),
            "completed_count": 0,
            "agreement_rate": None,
            "match_disagreement_count": None,
            "judge_false_match": None,
            "judge_false_nonmatch": None,
        },
        "latency": latency,
        "latency_limitations": [
            "Gold and planner call-level median/p95 were not frozen before a downstream matcher protocol failure."
            if resume_requested
            else "none",
            "Stage wall time is not a substitute for per-call latency and includes model loading overhead."
            if gold_stage_wall_ms is not None or planner_stage_wall_ms is not None
            else "none",
        ],
        "independence": {
            "gold_author_model": gold_model,
            "gold_author_prompt_sha256": _fixed_prompt_hash(GOLD_SYSTEM_PROMPT),
            "planner_model": planner_model,
            "planner_prompt_sha256": _fixed_prompt_hash(PLANNER_SYSTEM_PROMPT),
            "matcher_model": matcher_model,
            "matcher_prompt_sha256": _fixed_prompt_hash(MATCHER_SYSTEM_PROMPT),
            "human_reviewer": "kimdh_user",
            "gold_frozen_before_planner": True,
            "planner_output_visible_to_gold_author": False,
        },
        "contextual_signal_a_baselines": {
            "conservative_canary_recall": {"successes": 20, "total": 50},
            "conservative_canary_precision": {"successes": 17, "total": 22},
            "conservative_dev_recall": {"successes": 16, "total": 59},
            "conservative_dev_precision": {"successes": 23, "total": 24},
            "note": "Context only; earlier Signal A slots used a different proxy gold unit.",
        },
        "scope": {
            "runtime_or_canonical_promotion": False,
            "retrieval_changed": False,
            "reranker_changed": False,
            "answer_generation_changed": False,
            "training": False,
            "new_keyword_lists": False,
            "new_sealed_canary": False,
            "frozen_blind_accessed": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / f"semantic_requirement_planner_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = root / "reports/v3" / f"semantic_requirement_planner_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "model_runtime": model_metadata,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "artifacts": {
            "gold_overlay": {"path": _relative(root, gold_path), "sha256": gold_sha, "row_count": len(gold_rows)},
            "gold_manifest": {"path": _relative(root, gold_manifest_path), "sha256": gold_manifest_sha},
            "planner_outputs": {"path": _relative(root, planner_path), "sha256": planner_sha, "row_count": len(planner_rows)},
            "matches": {"path": _relative(root, match_path), "sha256": match_sha, "row_count": len(match_rows)},
            "human_review_packet": {"path": _relative(root, review_path), "sha256": review_sha, "row_count": len(review_rows)},
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {"path": _relative(root, markdown_path), "sha256": markdown_sha},
        },
        "decision": report["decision"],
    }
    if prior_report_path is not None:
        manifest["latency_provenance"] = {
            "path": _relative(root, prior_report_path),
            "sha256": file_sha256(prior_report_path),
        }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / f"semantic_requirement_planner_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during evaluation: {name}")
    return {
        "decision": report["decision"],
        "automatic_gates_pass": automatic_gates_pass,
        "metrics": primary,
        "gold_overlay": str(gold_path),
        "gold_sha256": gold_sha,
        "planner_outputs": str(planner_path),
        "planner_sha256": planner_sha,
        "matches": str(match_path),
        "matches_sha256": match_sha,
        "review_packet": str(review_path),
        "review_sha256": review_sha,
        "report": str(report_path),
        "report_sha256": report_sha,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate semantic requirement planning")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--gold-model", default=DEFAULT_GOLD_MODEL)
    parser.add_argument("--planner-model", default=DEFAULT_PLANNER_MODEL)
    parser.add_argument("--matcher-model", default=DEFAULT_MATCHER_MODEL)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--evaluated-at")
    parser.add_argument("--frozen-gold-overlay", type=Path)
    parser.add_argument("--frozen-gold-manifest", type=Path)
    parser.add_argument("--frozen-planner-outputs", type=Path)
    parser.add_argument("--frozen-matches", type=Path)
    parser.add_argument("--prior-report", type=Path)
    parser.add_argument("--gold-stage-wall-ms", type=float)
    parser.add_argument("--planner-stage-wall-ms", type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        gold_model=args.gold_model,
        planner_model=args.planner_model,
        matcher_model=args.matcher_model,
        batch_size=args.batch_size,
        timeout=args.timeout,
        evaluated_at=args.evaluated_at,
        frozen_gold_overlay=args.frozen_gold_overlay,
        frozen_gold_manifest=args.frozen_gold_manifest,
        frozen_planner_outputs=args.frozen_planner_outputs,
        frozen_matches=args.frozen_matches,
        prior_report=args.prior_report,
        gold_stage_wall_ms=args.gold_stage_wall_ms,
        planner_stage_wall_ms=args.planner_stage_wall_ms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
