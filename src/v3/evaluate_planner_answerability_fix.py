from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.evaluate_semantic_requirement_planner import (
    DEFAULT_CANARY,
    DEFAULT_CEILING,
    DEFAULT_DEV,
    DEFAULT_PLANNER_MODEL,
    PLANNER_SYSTEM_PROMPT,
    _fixed_prompt_hash,
    build_population,
    call_structured,
    runtime_metadata,
)


EVALUATOR_VERSION = "semantic-planner-answerability-fix-v3.0"
GROUND_TRUTH_SCHEMA_VERSION = "semantic-answerability-ground-truth-v3.0"
OUTPUT_SCHEMA_VERSION = "semantic-planner-answerability-output-v3.0"
REPORT_SCHEMA_VERSION = "semantic-planner-answerability-report-v3.0"
MANIFEST_SCHEMA_VERSION = "semantic-planner-answerability-manifest-v3.0"

DEFAULT_BASELINE = Path(
    "data/v3/evaluation/semantic_requirement_planner_outputs_"
    "e82122d0d473f9f956f03911690eebba5a35d474e40e58f2b769d9866dfc9c1c.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/semantic_planner_answerability_fix.md")


ANSWERABILITY_SYSTEM_PROMPT = """당신은 Planner A 내부의 문서 답변 가능성 분류기다.
requirement는 이미 atomic하게 확정됐다. 추가·삭제·병합·분해·이름변경·재작성·
순서변경을 절대 하지 말고, 각 requirement_index마다 boolean 하나만 반환한다.

반드시 원 질문 전체와 해당 requirement를 함께 읽고 다음 순서로 판정한다.
1. 요구 값이 사용자의 비공개 계정·캐릭터·인벤토리·세팅·잔액·사용기록에
   의존하는가? 현재 경매장 등 실시간 외부 상태인가? 사용자에게 최선/이득인지
   같은 맞춤 추천·주관 판단·미래 예측인가? 던파 외부 정보나 시스템 프롬프트·
   내부 평가 정보인가? 그렇다면 answerable_from_docs=false다.
2. 그 외에 던파의 공식 정책·상품 조건·가격·삭제일·거래타입·구매제한·제재
   단계·이벤트 기간·가이드 규칙·FAQ 규칙·공지 사실·패치 동작을 묻는가?
   그렇다면 answerable_from_docs=true다. 현재 입력에 근거 문서가 없거나 실제
   검색이 실패할 수 있어도 질문 유형이 공식 사실이면 true다.

한 질문 안에 true와 false가 섞일 수 있다. 원 질문의 '내 상황에 맞게' 같은
개인 귀속은 그 판단 requirement에도 적용해야 하며, 옆의 공식 사실 requirement로
번지게 해서는 안 된다. 반대로 정책 문장이 조건부이거나 예/아니오 형태이거나
불확실하게 들린다는 이유만으로 false로 만들지 않는다. 던파 문서를 참고하라는
표현이 있어도 요청 자체가 개인·실시간·주관·예측·범위 밖이면 false다.

예시:
- "내 계정의 현재 제재 상태" → false / "공개된 이용제한 단계" → true
- "현재 경매장 웨딩 아바타 시세" → false / "골드 코인 10개의 공식 가격" → true
- "내 세팅을 바꾸는 게 최선인가" → false / "무력화 게이지 차감 시 결과" → true
- "내 PC에서 오류가 재발할까" → false / "공식 오류 처리 상태" → true

분류만 수행한다. 질문에 답하거나 근거를 검색하거나 설명문을 생성하지 않는다."""


class AnswerabilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_index: int = Field(ge=1, le=8)
    answerable_from_docs: bool


class AnswerabilityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    decisions: list[AnswerabilityDecision] = Field(min_length=1, max_length=8)


class AnswerabilityBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[AnswerabilityCase] = Field(min_length=1, max_length=8)


OFFICIAL_FACT_FALSE_LABEL_IDS = {
    "authored_canary_sha256_20e5356688ba7d0b4a4c0c1d21c7263f39468fbe4d0c051ba8e640402605e755",
    "authored_canary_sha256_73b2f702259ffdf8b732aa13bd9b7f2733cca4a5641aafd723db75f87d9bf88c",
    "authored_canary_sha256_d2027332c0a4ec074681ccdb828d8dcca4613fc47884803c49faf73b36a44886",
}


PARTIAL_REQUIREMENT_TRUTH: dict[str, list[tuple[str, bool]]] = {
    "authored_canary_sha256_09d9774ed3e7ac99faddfd10bd2c6bb0d52fc29088570a850641700e6937f337": [
        ("화면 표시 오류의 공식 처리 상태", True),
        ("사용자 PC에서의 재발 가능성 판단", False),
    ],
    "authored_canary_sha256_2da2c7cab1f609754b2910c8e7f168b7f140b0b41a54a503c5e63f9e18fa0995": [
        ("과실복구 신청 경로", True),
        ("신청 시 작성할 내용", True),
        ("사용자 실수의 실제 복구 대상 여부", False),
    ],
    "authored_canary_sha256_5edb1f1854d2a8b2d7e71e485e0cc9d0c89bb55a1187c7239b6684c758fe265b": [
        ("황금 큐브의 공식 효과", True),
        ("사용자 장비 세팅에 최선인지 판단", False),
    ],
    "authored_canary_sha256_9e2c7f69dd204fd5229a8e21b441b7d2c07b3e4ba5eb73ee5b40f5867f4bb875": [
        ("마일리지 소멸 시점", True),
        ("일일 마일리지 획득 한도", True),
        ("사용자의 남은 마일리지 계산", False),
    ],
    "authored_canary_sha256_a3a0c0f5317a0602ffd229d014f3539bee6f559a33e221d457cb202ec816a6fa": [
        ("흑아 태초 이관서 획득 방법", True),
        ("사용자 악세서리에 이득인지 판단", False),
    ],
    "retrieval_dev_sha256_144296d937ab23d899b3375c994f2e6568b4a9febb2beb18a68de0a89465c047": [
        ("사용자 계정에서 브레이커 육성이 최선인지 판단", False),
    ],
    "retrieval_dev_sha256_2351c7b115704a5b052bf55b5ca00c74f1851342f17fd98e37a92b1aee851d18": [
        ("두 보급품의 공식 사용 가능 캐릭터", True),
        ("사용자가 브레이커를 키우는 것이 좋은지 판단", False),
    ],
    "retrieval_dev_sha256_5d048cff165a5862fcdbdd2784097eeaf10fbe1f4b9facdb99565b67729d7939": [
        ("세라의 공식 현금 가치", True),
        ("세라샵의 공식 구매 가능 품목", True),
        ("사용자가 지금 충전하는 것이 좋은지 판단", False),
    ],
    "retrieval_dev_sha256_96736fb482a1d58fc401bc329c3d24f93741ffa8d91440338b7fdb7ed59e05de": [
        ("외부 결제 요구의 공식 확인·신고 방법", True),
        ("사용자가 받은 실제 연락의 진위 판단", False),
    ],
    "retrieval_dev_sha256_a572774c7bbcb8c10ac867faf5071725daaece00c8c43682886d6a1f5b7ffd4a": [
        ("일반 우편 보관 기간", True),
        ("경매장 구매 우편 보관 기간", True),
        ("사용자가 지금 바로 수령해야 하는지 판단", False),
    ],
    "retrieval_dev_sha256_ac2eb45b07457cc2142e716afd6da6f0aad52a35598442fda9810271dda7b842": [
        ("무력화 게이지 전부 차감 시 공식 결과", True),
        ("사용자가 세팅을 바꿔야 하는지 판단", False),
    ],
    "retrieval_dev_sha256_bad06d84865648fcf4702d7117102cf68d11f24f448dcee9b9ca14c623e90f1d": [
        ("기초 데이터 획득 던전", True),
        ("사용자 캐릭터에 좋은 던전 추천", False),
    ],
    "retrieval_dev_sha256_d946d602ed9908e07789d3782cedf36efa3d45c91631cf785c193268c47475c2": [
        ("마법부여 상점 설치 방법", True),
        ("사용자 상황에 맞는 수수료 결정", False),
        ("사용자 상황에 맞는 설치 위치 결정", False),
    ],
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_answerability_ground_truth(
    population: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    partial_ids = set()
    for item in population:
        label = item["answerability_label"]
        if label == "true":
            profile = "docs_only"
            default = True
            requirements: list[dict[str, Any]] = []
        elif label == "false":
            if item["case_id"] in OFFICIAL_FACT_FALSE_LABEL_IDS:
                profile = "docs_only_official_fact_without_current_evidence"
                default = True
            else:
                profile = "non_docs_only"
                default = False
            requirements = []
        elif label == "partial":
            profile = "mixed"
            default = None
            partial_ids.add(item["case_id"])
            if item["case_id"] not in PARTIAL_REQUIREMENT_TRUTH:
                raise RuntimeError(f"Missing partial ground truth: {item['case_id']}")
            requirements = [
                {
                    "requirement_index": index,
                    "requirement_summary": summary,
                    "answerable_from_docs": expected,
                }
                for index, (summary, expected) in enumerate(
                    PARTIAL_REQUIREMENT_TRUTH[item["case_id"]], 1
                )
            ]
        else:
            raise RuntimeError(f"Unexpected answerability label: {label!r}")
        rows.append(
            {
                "ground_truth_schema_version": GROUND_TRUTH_SCHEMA_VERSION,
                "case_id": item["case_id"],
                "dataset": item["dataset"],
                "question": item["question"],
                "source_ids": item["source_ids"],
                "answerability_label": label,
                "answerability_profile": profile,
                "default_requirement_answerable_from_docs": default,
                "partial_requirements_in_question_order": requirements,
                "ground_truth_origin": (
                    "question_type_contract_official_fact_true"
                    if item["case_id"] in OFFICIAL_FACT_FALSE_LABEL_IDS
                    else "preexisting_human_reviewed_answerability_label_and_question_type_contract"
                    if label != "partial"
                    else "preexisting_human_reviewed_question_and_gold_answer_bounded_overlay"
                ),
                "new_planner_output_visible_during_ground_truth_authoring": False,
            }
        )
    if partial_ids != set(PARTIAL_REQUIREMENT_TRUTH):
        raise RuntimeError("Partial ground-truth mapping does not match the frozen population")
    return sorted(rows, key=lambda row: row["case_id"])


def answerability_prompt(
    population_batch: list[dict[str, Any]],
    baseline_by_id: dict[str, dict[str, Any]],
) -> str:
    payload = []
    for case_index, item in enumerate(population_batch, 1):
        requirements = []
        for requirement_index, requirement in enumerate(
            baseline_by_id[item["case_id"]]["requirements"], 1
        ):
            requirements.append(
                {
                    "requirement_index": requirement_index,
                    "subject": requirement["subject"],
                    "relation": requirement["relation"],
                    "value_type": requirement["value_type"],
                    "subject_group": requirement["subject_group"],
                    "qualifiers": requirement.get("qualifiers", []),
                    "time_scope": requirement.get("time_scope"),
                    "coordination_scope": requirement.get("coordination_scope"),
                }
            )
        payload.append(
            {
                "case_id": f"case_{case_index}",
                "question": item["question"],
                "frozen_requirements": requirements,
                "expected_decision_count": len(requirements),
            }
        )
    return "Classify these frozen requirements:\n" + json.dumps(
        payload, ensure_ascii=False, sort_keys=True
    )


def run_answerability_classifier(
    population: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    *,
    model: str,
    batch_size: int,
    timeout: float,
    caller: Callable[..., tuple[BaseModel, dict[str, Any]]] = call_structured,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    baseline_by_id = {row["case_id"]: row for row in baseline_rows}
    output = []
    call_logs = []
    for start in range(0, len(population), batch_size):
        batch = population[start : start + batch_size]
        parsed, call_log = caller(
            model=model,
            system_prompt=ANSWERABILITY_SYSTEM_PROMPT,
            user_prompt=answerability_prompt(batch, baseline_by_id),
            output_type=AnswerabilityBatchOutput,
            timeout=timeout,
        )
        cases = {case.case_id: case.model_dump() for case in parsed.cases}
        expected_case_ids = {
            f"case_{index}" for index in range(1, len(batch) + 1)
        }
        if set(cases) != expected_case_ids:
            raise RuntimeError(
                "Answerability classifier returned missing or unexpected case ids"
            )
        for case_index, item in enumerate(batch, 1):
            baseline = baseline_by_id[item["case_id"]]
            decisions = cases[f"case_{case_index}"]["decisions"]
            decision_by_index = {
                decision["requirement_index"]: decision for decision in decisions
            }
            expected_indices = set(range(1, len(baseline["requirements"]) + 1))
            if set(decision_by_index) != expected_indices or len(decisions) != len(
                expected_indices
            ):
                raise RuntimeError(
                    f"Incomplete answerability decisions: {item['case_id']}"
                )
            row = json.loads(json.dumps(baseline, ensure_ascii=False))
            row["answerability_classifier_version"] = EVALUATOR_VERSION
            for requirement_index, requirement in enumerate(
                row["requirements"], 1
            ):
                requirement["answerable_from_docs"] = decision_by_index[
                    requirement_index
                ]["answerable_from_docs"]
            output.append(row)
        call_logs.append(call_log)
    return sorted(output, key=lambda row: row["case_id"]), call_logs


def _expected_flags(
    truth: dict[str, Any], prediction_count: int
) -> list[bool]:
    default = truth["default_requirement_answerable_from_docs"]
    if default is not None:
        return [bool(default)] * prediction_count
    return [
        bool(row["answerable_from_docs"])
        for row in truth["partial_requirements_in_question_order"]
    ]


def score_answerability(
    planner_rows: list[dict[str, Any]], truth_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    truth_by_id = {row["case_id"]: row for row in truth_rows}
    diagnostics = []
    for row in sorted(planner_rows, key=lambda item: item["case_id"]):
        truth = truth_by_id[row["case_id"]]
        predicted = [
            bool(requirement["answerable_from_docs"])
            for requirement in row["requirements"]
        ]
        expected = _expected_flags(truth, len(predicted))
        aligned = min(len(predicted), len(expected))
        false_positive_indices = [
            index + 1
            for index in range(aligned)
            if predicted[index] and not expected[index]
        ]
        false_negative_indices = [
            index + 1
            for index in range(aligned)
            if not predicted[index] and expected[index]
        ]
        diagnostics.append(
            {
                "case_id": row["case_id"],
                "dataset": truth["dataset"],
                "source_ids": truth["source_ids"],
                "answerability_profile": truth["answerability_profile"],
                "prediction_count": len(predicted),
                "expected_count": len(expected),
                "predicted_flags": predicted,
                "expected_flags": expected,
                "docs_false_positive_indices": false_positive_indices,
                "docs_false_negative_indices": false_negative_indices,
                "missing_expected_requirement_count": max(0, len(expected) - len(predicted)),
                "extra_unaligned_prediction_count": max(0, len(predicted) - len(expected)),
            }
        )

    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "question_count": len(rows),
            "docs_false_positive_count": sum(
                len(row["docs_false_positive_indices"]) for row in rows
            ),
            "docs_false_positive_question_count": sum(
                bool(row["docs_false_positive_indices"]) for row in rows
            ),
            "docs_false_negative_count": sum(
                len(row["docs_false_negative_indices"]) for row in rows
            ),
            "docs_false_negative_question_count": sum(
                bool(row["docs_false_negative_indices"]) for row in rows
            ),
            "missing_expected_requirement_count": sum(
                row["missing_expected_requirement_count"] for row in rows
            ),
            "extra_unaligned_prediction_count": sum(
                row["extra_unaligned_prediction_count"] for row in rows
            ),
            "fully_correct_question_count": sum(
                not row["docs_false_positive_indices"]
                and not row["docs_false_negative_indices"]
                and row["missing_expected_requirement_count"] == 0
                and row["extra_unaligned_prediction_count"] == 0
                for row in rows
            ),
        }

    metrics: dict[str, Any] = {"overall": aggregate(diagnostics)}
    for dataset in ("downgraded_canary_32", "adaptive_dev_63"):
        metrics[dataset] = aggregate(
            [row for row in diagnostics if row["dataset"] == dataset]
        )
    metrics["claim_ceiling_stress_15"] = aggregate(
        [
            row
            for row, truth in zip(diagnostics, truth_rows, strict=True)
            if truth.get("claim_ceiling_stress_slice")
        ]
    )
    sources = sorted({source for row in diagnostics for source in row["source_ids"]})
    metrics["by_source"] = {
        source: aggregate(
            [row for row in diagnostics if source in row["source_ids"]]
        )
        for source in sources
    }
    return diagnostics, metrics


def requirement_projection(row: dict[str, Any]) -> list[dict[str, Any]]:
    ignored = {"answerable_from_docs", "requirement_id"}
    return [
        {key: value for key, value in requirement.items() if key not in ignored}
        for requirement in row["requirements"]
    ]


def compare_requirement_regression(
    baseline_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    baseline = {row["case_id"]: row for row in baseline_rows}
    new = {row["case_id"]: row for row in new_rows}
    if set(baseline) != set(new):
        raise RuntimeError("Baseline and new planner case ids differ")
    rows = []
    for case_id in sorted(baseline):
        before = requirement_projection(baseline[case_id])
        after = requirement_projection(new[case_id])
        if before == after:
            status = "unchanged"
        elif len(before) != len(after):
            status = "count_changed"
        else:
            status = "content_changed"
        rows.append(
            {
                "case_id": case_id,
                "status": status,
                "baseline_requirement_count": len(before),
                "new_requirement_count": len(after),
                "baseline_projection_sha256": _sha256_bytes(
                    _canonical_json_bytes(before)
                ),
                "new_projection_sha256": _sha256_bytes(_canonical_json_bytes(after)),
            }
        )
    return rows, {
        "question_count": len(rows),
        "unchanged_question_count": sum(row["status"] == "unchanged" for row in rows),
        "count_changed_question_count": sum(
            row["status"] == "count_changed" for row in rows
        ),
        "content_changed_question_count": sum(
            row["status"] == "content_changed" for row in rows
        ),
        "requirement_regression_count": sum(
            row["status"] != "unchanged" for row in rows
        ),
    }


def _latency(logs: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(float(row["latency_ms"]) for row in logs)
    return {
        "call_count": len(values),
        "median_ms": round(statistics.median(values), 3) if values else None,
        "p95_ms": values[min(len(values) - 1, int(len(values) * 0.95))]
        if values
        else None,
        "total_ms": round(sum(values), 3) if values else None,
    }


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _markdown(report: dict[str, Any]) -> bytes:
    before = report["metrics"]["baseline"]["overall"]
    after = report["metrics"]["after"]["overall"]
    regression = report["requirement_regression"]
    lines = [
        "# Planner answerability-only fix",
        "",
        f"- Decision: **{report['decision']}**",
        f"- docs false positives: {before['docs_false_positive_count']} -> {after['docs_false_positive_count']}",
        f"- docs false negatives: {before['docs_false_negative_count']} -> {after['docs_false_negative_count']}",
        f"- exact requirement regressions: {regression['requirement_regression_count']}/{regression['question_count']}",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- {name}: {value}" for name, value in report["gates"].items())
    lines.extend(
        [
            "",
            "Strong recall is an externally confirmed upstream decision and was not",
            "re-measured with the rejected 4B gold/matcher artifacts in this cycle.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def evaluate_and_freeze(
    root: Path,
    *,
    model: str = DEFAULT_PLANNER_MODEL,
    batch_size: int = 5,
    timeout: float = 240.0,
    evaluated_at: str | None = None,
    frozen_new_output: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    input_paths = {
        "canary_32": root / DEFAULT_CANARY,
        "adaptive_dev_63": root / DEFAULT_DEV,
        "claim_ceiling_15": root / DEFAULT_CEILING,
        "baseline_planner": root / DEFAULT_BASELINE,
        "contract": root / DEFAULT_CONTRACT,
        "planner_source": root / "src/v3/evaluate_semantic_requirement_planner.py",
        "evaluator_source": Path(__file__).resolve(),
    }
    input_hashes = {name: file_sha256(path) for name, path in input_paths.items()}
    population = build_population(
        read_jsonl(input_paths["canary_32"]),
        read_jsonl(input_paths["adaptive_dev_63"]),
        read_jsonl(input_paths["claim_ceiling_15"]),
    )
    ceiling_ids = {
        str(row.get("case_id")) for row in read_jsonl(input_paths["claim_ceiling_15"])
    }

    truth_rows = build_answerability_ground_truth(population)
    for row in truth_rows:
        row["claim_ceiling_stress_slice"] = row["case_id"] in ceiling_ids
    truth_bytes = _serialize_jsonl(truth_rows, lambda row: row["case_id"])
    truth_sha = _sha256_bytes(truth_bytes)
    truth_path = root / "data/v3/evaluation" / (
        f"semantic_answerability_ground_truth_{truth_sha}.jsonl"
    )
    write_immutable(truth_path, truth_bytes)

    model_meta = runtime_metadata(model, timeout)
    baseline_rows = read_jsonl(input_paths["baseline_planner"])
    if frozen_new_output is None:
        new_rows, call_logs = run_answerability_classifier(
            population,
            baseline_rows,
            model=model,
            batch_size=batch_size,
            timeout=timeout,
        )
        new_bytes = _serialize_jsonl(new_rows, lambda row: row["case_id"])
        new_sha = _sha256_bytes(new_bytes)
        new_path = root / "data/v3/evaluation" / (
            f"semantic_requirement_planner_answerability_outputs_{new_sha}.jsonl"
        )
        write_immutable(new_path, new_bytes)
    else:
        new_path = (root / frozen_new_output).resolve()
        new_rows = read_jsonl(new_path)
        new_sha = file_sha256(new_path)
        call_logs = []

    baseline_diagnostics, baseline_metrics = score_answerability(
        baseline_rows, truth_rows
    )
    new_diagnostics, new_metrics = score_answerability(new_rows, truth_rows)
    regression_rows, regression = compare_requirement_regression(
        baseline_rows, new_rows
    )

    diagnostics = []
    baseline_by_id = {row["case_id"]: row for row in baseline_diagnostics}
    new_by_id = {row["case_id"]: row for row in new_diagnostics}
    regression_by_id = {row["case_id"]: row for row in regression_rows}
    for case_id in sorted(baseline_by_id):
        diagnostics.append(
            {
                "case_id": case_id,
                "baseline": baseline_by_id[case_id],
                "after": new_by_id[case_id],
                "requirement_diff": regression_by_id[case_id],
            }
        )
    diagnostics_bytes = _serialize_jsonl(diagnostics, lambda row: row["case_id"])
    diagnostics_sha = _sha256_bytes(diagnostics_bytes)
    diagnostics_path = root / "data/v3/evaluation" / (
        f"semantic_planner_answerability_diagnostics_{diagnostics_sha}.jsonl"
    )
    write_immutable(diagnostics_path, diagnostics_bytes)

    gates = {
        "docs_false_positive_zero": new_metrics["overall"][
            "docs_false_positive_count"
        ]
        == 0,
        "requirement_regression_zero": regression["requirement_regression_count"]
        == 0,
    }
    go = all(gates.values())
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "development_only_answerability_fix",
        "decision": "GO_TO_RERANKER_PILOT" if go else "NO_GO_REQUIRES_PROMPT_READJUSTMENT",
        "gates": gates,
        "metrics": {"baseline": baseline_metrics, "after": new_metrics},
        "requirement_regression": regression,
        "ground_truth": {
            "independence": "frozen_before_new_planner_run",
            "truth_definition": "official_DNF_fact_true_private_realtime_subjective_OOD_false",
            "true_false_source": "preexisting_human_reviewed_label_plus_question_type_contract",
            "partial_source": "preexisting_human_reviewed_question_and_gold_answer_bounded_overlay",
            "partial_alignment": "question_order_atomic_requirement_ordinal",
            "four_b_gold_or_matcher_used": False,
        },
        "strong_recall_status": {
            "status": "accepted_user_confirmed_upstream_decision_not_reproduced_this_cycle",
            "downgraded_canary_32_approximate": 0.90,
            "adaptive_dev_63_approximate": 0.98,
        },
        "planner": {
            "model": model_meta,
            "enumeration_prompt_sha256": _fixed_prompt_hash(
                PLANNER_SYSTEM_PROMPT
            ),
            "answerability_prompt_sha256": _fixed_prompt_hash(
                ANSWERABILITY_SYSTEM_PROMPT
            ),
            "enumeration_source": "frozen_baseline_output_for_same_95_evaluation",
            "latency": _latency(call_logs),
        },
        "scope": {
            "planner_prompt_only": True,
            "requirement_enumeration_logic_changed": False,
            "frozen_requirement_text_reused": True,
            "reranker_implemented": False,
            "entailment_judge_implemented": False,
            "answer_generation_implemented": False,
            "training": False,
            "runtime_keyword_list_added": False,
            "freeform_generation": False,
            "frozen_blind_accessed": False,
            "runtime_or_canonical_promotion": False,
        },
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / (
        f"semantic_planner_answerability_fix_{report_sha}.json"
    )
    write_immutable(report_path, report_bytes)
    markdown_bytes = _markdown(report)
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = root / "reports/v3" / (
        f"semantic_planner_answerability_fix_{markdown_sha}.md"
    )
    write_immutable(markdown_path, markdown_bytes)

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "source_commit": _git_head(root),
        "inputs": {
            name: {"path": _relative(root, path), "sha256": input_hashes[name]}
            for name, path in input_paths.items()
        },
        "model": model_meta,
        "planner_enumeration_prompt_sha256": _fixed_prompt_hash(
            PLANNER_SYSTEM_PROMPT
        ),
        "planner_answerability_prompt_sha256": _fixed_prompt_hash(
            ANSWERABILITY_SYSTEM_PROMPT
        ),
        "artifacts": {
            "ground_truth": {
                "path": _relative(root, truth_path),
                "sha256": truth_sha,
                "row_count": len(truth_rows),
            },
            "planner_outputs": {
                "path": _relative(root, new_path),
                "sha256": new_sha,
                "row_count": len(new_rows),
            },
            "diagnostics": {
                "path": _relative(root, diagnostics_path),
                "sha256": diagnostics_sha,
                "row_count": len(diagnostics),
            },
            "report": {"path": _relative(root, report_path), "sha256": report_sha},
            "report_markdown": {
                "path": _relative(root, markdown_path),
                "sha256": markdown_sha,
            },
        },
        "decision": report["decision"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / (
        f"semantic_planner_answerability_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    for name, path in input_paths.items():
        if file_sha256(path) != input_hashes[name]:
            raise RuntimeError(f"Input changed during answerability evaluation: {name}")
    return {
        "decision": report["decision"],
        "gates": gates,
        "baseline": baseline_metrics["overall"],
        "after": new_metrics["overall"],
        "requirement_regression": regression,
        "planner_output": str(new_path),
        "planner_output_sha256": new_sha,
        "ground_truth": str(truth_path),
        "ground_truth_sha256": truth_sha,
        "diagnostics": str(diagnostics_path),
        "diagnostics_sha256": diagnostics_sha,
        "report": str(report_path),
        "report_sha256": report_sha,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the planner answerable_from_docs-only prompt fix"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default=DEFAULT_PLANNER_MODEL)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--evaluated-at")
    parser.add_argument("--frozen-new-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = evaluate_and_freeze(
        args.root,
        model=args.model,
        batch_size=args.batch_size,
        timeout=args.timeout,
        evaluated_at=args.evaluated_at,
        frozen_new_output=args.frozen_new_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
