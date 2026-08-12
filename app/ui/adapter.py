from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


VALID_STATUSES = {
    "answer",
    "partial",
    "clarification",
    "unsupported",
    "error",
}

FAILURE_STAGE_LABELS = {
    "S1": "검색",
    "S2": "evidence pack 선택",
    "S3": "생성",
    "S4": "verifier 과차단",
    "S5": "의미·관계 오연결",
    "S?": "단계 미확정",
}


@dataclass(frozen=True)
class Citation:
    evidence_ref: str
    title: str
    locator_id: str
    start_char: int | None
    end_char: int | None
    text: str
    canonical_url: str
    source_id: str
    published_at: str
    valid_from: str
    valid_to: str
    status: str


@dataclass(frozen=True)
class ClarificationOption:
    option_id: str
    title: str
    parent_document_id: str
    candidate_ref: str


@dataclass(frozen=True)
class FailureStage:
    code: str
    label: str


@dataclass(frozen=True)
class JudgmentSignals:
    correct: bool | None
    false_full: bool | None
    unsupported_overclaim: bool | None


@dataclass(frozen=True)
class Judgment:
    outcome: str
    source: str
    failure_stages: tuple[FailureStage, ...]
    automatic: JudgmentSignals
    human: JudgmentSignals | None
    rationale: str
    reviewer_id: str
    reviewed_at: str


@dataclass(frozen=True)
class ResultSetMetadata:
    kind: str
    label: str
    case_count: int | None
    executed_at: str
    manifest_sha256: str
    one_shot_sha256: str
    frozen_set_sha256: str
    question_commit_sha256: str
    score_claimed: bool
    rerun_allowed: bool
    automatic_correct_count: int | None
    human_correct_count: int | None
    failed_count: int | None
    gold_error_count: int | None

    @property
    def automatic_accuracy(self) -> float | None:
        if not self.case_count or self.automatic_correct_count is None:
            return None
        return self.automatic_correct_count / self.case_count

    @property
    def human_accuracy(self) -> float | None:
        if not self.case_count or self.human_correct_count is None:
            return None
        return self.human_correct_count / self.case_count

    @property
    def accuracy_gap_percentage_points(self) -> float | None:
        automatic = self.automatic_accuracy
        human = self.human_accuracy
        if automatic is None or human is None:
            return None
        return (human - automatic) * 100


@dataclass(frozen=True)
class AnswerViewModel:
    status: str
    question_text: str
    answer_text: str
    verified_claim_count: int
    rejected_claim_count: int
    citations: tuple[Citation, ...]
    options: tuple[ClarificationOption, ...]
    total_seconds: float
    generation_seconds: float
    error_message: str
    judgment: Judgment | None
    set_metadata: ResultSetMetadata | None
    developer: dict[str, Any]


def to_view_model(
    payload: Mapping[str, Any],
    *,
    set_metadata: Mapping[str, Any] | ResultSetMetadata | None = None,
    failure_stages: Sequence[str | Mapping[str, Any]] = (),
    human_override: Mapping[str, Any] | None = None,
) -> AnswerViewModel:
    """Normalize a live response or a stored evaluation record for the UI."""

    record = _require_mapping(payload, "payload")
    nested_result = record.get("result")
    source = (
        _require_mapping(nested_result, "payload.result")
        if nested_result is not None
        else record
    )

    raw_mode = _text(
        source.get("mode")
        or source.get("response_mode")
        or record.get("actual_mode")
        or "unsupported"
    )
    error_message = _text(source.get("error") or record.get("error"))
    if error_message:
        status = "error"
    elif raw_mode in VALID_STATUSES:
        status = raw_mode
    else:
        status = "error"
        error_message = f"지원하지 않는 응답 mode: {raw_mode}"

    latency = source.get("latency") or {}
    latency_map = _require_mapping(latency, "latency")
    total_ms = _number(latency_map.get("total_ms") or source.get("latency_ms"))
    generation_ms = _number(latency_map.get("generation_ms"))

    judgment = _to_judgment(
        record,
        failure_stages=failure_stages,
        human_override=human_override,
    )
    metadata = _to_set_metadata(set_metadata)

    return AnswerViewModel(
        status=status,
        question_text=_text(
            source.get("question")
            or record.get("question")
            or record.get("question_text")
        ),
        answer_text=_text(source.get("rendered_answer")),
        verified_claim_count=len(
            _mapping_list(source.get("claims"), "claims")
        ),
        rejected_claim_count=len(
            _mapping_list(source.get("rejected_claims"), "rejected_claims")
        ),
        citations=tuple(_extract_citations(source, record)),
        options=tuple(_extract_options(source)),
        total_seconds=total_ms / 1000,
        generation_seconds=generation_ms / 1000,
        error_message=error_message,
        judgment=judgment,
        set_metadata=metadata,
        developer={
            "candidates": copy.deepcopy(source.get("candidates") or []),
            "verification": copy.deepcopy(source.get("verification") or {}),
            "original_mode": raw_mode,
            "raw": copy.deepcopy(dict(record)),
        },
    )


def _extract_citations(
    source: Mapping[str, Any],
    record: Mapping[str, Any],
) -> list[Citation]:
    raw_citations: list[Mapping[str, Any]] = []
    if "claims" in source:
        for claim in _mapping_list(source.get("claims"), "claims"):
            raw_citations.extend(
                _mapping_list(claim.get("citations"), "claims[].citations")
            )
    elif "requirements" in source:
        for requirement in _mapping_list(
            source.get("requirements"), "requirements"
        ):
            raw_citations.extend(
                _mapping_list(
                    requirement.get("citations"),
                    "requirements[].citations",
                )
            )
    elif "citations_json" in record:
        raw_citations = _mapping_list(
            _json_value(record.get("citations_json"), "citations_json"),
            "citations_json",
        )

    return [
        Citation(
            evidence_ref=_text(item.get("evidence_ref")),
            title=_text(item.get("title")),
            locator_id=_text(item.get("chunk_id") or item.get("document_id")),
            start_char=_optional_int(item.get("start_char")),
            end_char=_optional_int(item.get("end_char")),
            text=_text(item.get("text")),
            canonical_url=_official_document_url(
                item.get("canonical_url") or item.get("url")
            ),
            source_id=_text(item.get("source_id")),
            published_at=_text(item.get("published_at")),
            valid_from=_text(item.get("valid_from")),
            valid_to=_text(item.get("valid_to")),
            status=_text(item.get("status")),
        )
        for item in raw_citations
    ]


def _extract_options(source: Mapping[str, Any]) -> list[ClarificationOption]:
    return [
        ClarificationOption(
            option_id=_text(item.get("option_id")),
            title=_text(item.get("title")),
            parent_document_id=_text(item.get("parent_document_id")),
            candidate_ref=_text(item.get("candidate_ref")),
        )
        for item in _mapping_list(
            source.get("clarification_options"),
            "clarification_options",
        )
    ]


def _to_judgment(
    record: Mapping[str, Any],
    *,
    failure_stages: Sequence[str | Mapping[str, Any]],
    human_override: Mapping[str, Any] | None,
) -> Judgment | None:
    automatic = JudgmentSignals(
        correct=_optional_bool(
            _first(record, "automatic_meaning_complete", "meaning_complete")
        ),
        false_full=_optional_bool(
            _first(record, "automatic_false_full", "false_full_candidate")
        ),
        unsupported_overclaim=_optional_bool(
            _first(
                record,
                "automatic_unsupported_overclaim",
                "unsupported_overclaim_candidate",
            )
        ),
    )

    human_values = dict(record)
    if human_override is not None:
        human_values.update(_require_mapping(human_override, "human_override"))
    human = JudgmentSignals(
        correct=_optional_bool(human_values.get("human_semantic_correct")),
        false_full=_optional_bool(human_values.get("human_false_full")),
        unsupported_overclaim=_optional_bool(
            human_values.get("human_unsupported_overclaim")
        ),
    )
    human_present = human_override is not None or any(
        value is not None
        for value in (
            human.correct,
            human.false_full,
            human.unsupported_overclaim,
        )
    )

    automatic_outcome = _outcome(automatic)
    human_outcome = _outcome(human) if human_present else "unreviewed"
    if human_outcome != "unreviewed":
        outcome = human_outcome
        source = "human"
    else:
        outcome = automatic_outcome
        source = "automatic" if outcome != "unreviewed" else "unreviewed"

    stages = _normalize_failure_stages(failure_stages)
    if outcome == "correct":
        stages = ()

    if outcome == "unreviewed" and not stages:
        return None
    return Judgment(
        outcome=outcome,
        source=source,
        failure_stages=stages,
        automatic=automatic,
        human=human if human_present else None,
        rationale=_text(
            human_values.get("rationale")
            or human_values.get("review_rationale")
        ),
        reviewer_id=_text(human_values.get("reviewer_id")),
        reviewed_at=_text(human_values.get("reviewed_at")),
    )


def _to_set_metadata(
    value: Mapping[str, Any] | ResultSetMetadata | None,
) -> ResultSetMetadata | None:
    if value is None or isinstance(value, ResultSetMetadata):
        return value
    item = _require_mapping(value, "set_metadata")
    kind = _text(item.get("kind"))
    if kind not in {"sealed_evaluation", "demonstration"}:
        raise ValueError(f"지원하지 않는 결과 세트 kind: {kind}")
    return ResultSetMetadata(
        kind=kind,
        label=_text(item.get("label")),
        case_count=_optional_int(item.get("case_count")),
        executed_at=_text(item.get("executed_at")),
        manifest_sha256=_text(item.get("manifest_sha256")),
        one_shot_sha256=_text(item.get("one_shot_sha256")),
        frozen_set_sha256=_text(item.get("frozen_set_sha256")),
        question_commit_sha256=_text(item.get("question_commit_sha256")),
        score_claimed=bool(_optional_bool(item.get("score_claimed"))),
        rerun_allowed=bool(_optional_bool(item.get("rerun_allowed"))),
        automatic_correct_count=_optional_int(
            item.get("automatic_correct_count")
        ),
        human_correct_count=_optional_int(item.get("human_correct_count")),
        failed_count=_optional_int(item.get("failed_count")),
        gold_error_count=_optional_int(item.get("gold_error_count")),
    )


def _normalize_failure_stages(
    values: Sequence[str | Mapping[str, Any]],
) -> tuple[FailureStage, ...]:
    stages: list[FailureStage] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, Mapping):
            code = _text(value.get("attribution_stage") or value.get("stage"))
        else:
            code = _text(value)
        if code not in FAILURE_STAGE_LABELS:
            raise ValueError(f"지원하지 않는 실패 단계: {code}")
        if code not in seen:
            stages.append(FailureStage(code, FAILURE_STAGE_LABELS[code]))
            seen.add(code)
    return tuple(stages)


def _outcome(signals: JudgmentSignals) -> str:
    if signals.correct is True and not (
        signals.false_full is True or signals.unsupported_overclaim is True
    ):
        return "correct"
    if (
        signals.correct is False
        or signals.false_full is True
        or signals.unsupported_overclaim is True
    ):
        return "failed"
    return "unreviewed"


def _mapping_list(value: Any, name: str) -> list[Mapping[str, Any]]:
    if value is None or value == "":
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be a list")
    return [_require_mapping(item, f"{name}[]") for item in value]


def _json_value(value: Any, name: str) -> Any:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} is not valid JSON") from exc
    return value


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _first(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _official_document_url(value: Any) -> str:
    url = _text(value)
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.hostname != "df.nexon.com"
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return url


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"boolean 값으로 해석할 수 없습니다: {value}")
