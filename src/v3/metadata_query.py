from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal


METADATA_QUERY_VERSION = "dnf-metadata-query-experimental-v3"
RUNTIME_SNAPSHOT_SCHEMA_VERSION = (
    "dnf_free_minimal_runtime_snapshot_v1"
)
DEFAULT_RUNTIME_SNAPSHOT = Path(
    "data/v3/runtime/free_minimal_runtime_snapshot_v1.json"
)

_COLLECTIONS = (
    {
        "source_id": "dnf_event",
        "aliases": ("이벤트", "행사"),
        "label": "이벤트",
        "latest_sort_field": "published_at",
    },
    {
        "source_id": "dnf_update",
        "aliases": ("업데이트", "패치"),
        "label": "업데이트",
        "latest_sort_field": "published_at",
    },
    {
        "source_id": "dnf_notice",
        "aliases": ("공지사항", "공지"),
        "label": "공지",
        "latest_sort_field": "published_at",
    },
)
_COLLECTION_BY_SOURCE = {
    row["source_id"]: row for row in _COLLECTIONS
}

_ACTIVE_CUES = (
    "지금",
    "현재",
    "진행중",
    "진행 중",
    "열려있는",
    "열려 있는",
)
_COUNT_CUES = ("몇개", "몇 개", "개수")
_ALL_CUES = ("전체", "모두", "총", "수집")
_LIST_CUES = ("목록", "리스트", "전부", "전체", "모두")
_LATEST_START_CUES = (
    "최근시작",
    "최근 시작",
    "가장최근시작",
    "가장 최근 시작",
    "제일최근시작",
    "제일 최근 시작",
    "최신시작",
    "최신 시작",
)
_AMBIGUOUS_LATEST_CUES = (
    "최신",
    "가장최근",
    "가장 최근",
    "제일최근",
    "제일 최근",
)
_LATEST_PUBLISHED_CUES = (
    "최근등록",
    "최근 등록",
    "최근게시",
    "최근 게시",
    "최근에올라온",
    "최근에 올라온",
    "가장최근에올라온",
    "가장 최근에 올라온",
)
_CONTENT_CUES = (
    "보상",
    "혜택",
    "참여방법",
    "참여 방법",
    "조건",
    "삭제",
    "아이템",
    "내용",
    "어떻게",
)


@dataclass(frozen=True)
class MetadataQueryPlan:
    mode: Literal["metadata", "clarification"]
    source_id: str
    operation: Literal["list_all", "count", "latest"] | None
    as_of: str
    active_only: bool
    sort_field: Literal["valid_from", "published_at", "valid_to"] | None
    clarification: str | None = None


@dataclass(frozen=True)
class MetadataFreshness:
    source_id: str
    requested_as_of: str
    coverage_as_of: str | None
    effective_as_of: str | None
    source_status: str | None
    status: Literal[
        "verified_to_requested",
        "bounded_to_snapshot",
        "unavailable",
    ]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_date(value: Any, *, field: str) -> str:
    normalized = str(value or "")
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {field}: {normalized}") from exc
    return normalized


def _manifest_input(
    manifest: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    matches = [
        row
        for row in manifest.get("inputs", [])
        if row.get("role") == role
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Missing manifest input: {role}")
    return matches[0]


def load_metadata_freshness_snapshot(
    *,
    root: Path,
    snapshot_path: Path = DEFAULT_RUNTIME_SNAPSHOT,
) -> dict[str, Any]:
    path = (
        snapshot_path
        if snapshot_path.is_absolute()
        else root / snapshot_path
    )
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("schema_version") != RUNTIME_SNAPSHOT_SCHEMA_VERSION:
        raise RuntimeError("Unsupported metadata freshness snapshot")
    artifacts = snapshot.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RuntimeError("Metadata freshness snapshot has no artifacts")
    artifacts_by_role: dict[str, Path] = {}
    artifact_rows_by_role: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        role = str(artifact.get("role") or "")
        artifact_path = root / str(artifact.get("path") or "")
        expected_sha = str(artifact.get("sha256") or "")
        if not role or role in artifacts_by_role:
            raise RuntimeError(
                "Metadata freshness artifact roles are invalid"
            )
        if (
            not artifact_path.is_file()
            or not expected_sha
            or _file_sha256(artifact_path) != expected_sha
        ):
            raise RuntimeError(
                f"Metadata freshness artifact mismatch: {artifact_path}"
            )
        artifacts_by_role[role] = artifact_path
        artifact_rows_by_role[role] = artifact
    required_roles = {
        "documents",
        "chunks",
        "bm25_manifest",
        "dense_manifest",
        "source_registry_manifest",
        "source_registry",
        "normalized_manifest",
        "chunk_corpus_manifest",
    }
    if not required_roles.issubset(artifacts_by_role):
        raise RuntimeError(
            "Metadata freshness snapshot is missing runtime artifacts"
        )
    source_coverage = snapshot.get("source_coverage")
    if not isinstance(source_coverage, dict):
        raise RuntimeError(
            "Metadata freshness snapshot has no source coverage"
        )
    if not set(_COLLECTION_BY_SOURCE).issubset(source_coverage):
        raise RuntimeError(
            "Metadata freshness snapshot is missing query sources"
        )
    registry_manifest = json.loads(
        artifacts_by_role["source_registry_manifest"].read_text(
            encoding="utf-8"
        )
    )
    registry_as_of = _validated_date(
        registry_manifest.get("policy_context", {}).get("as_of_date"),
        field="source_registry.policy_context.as_of_date",
    )
    registry_runs = {
        str(row.get("source_id") or ""): str(row.get("status") or "")
        for row in registry_manifest.get("source_runs", [])
    }

    def assert_reference(
        reference: dict[str, Any],
        *,
        artifact_role: str,
    ) -> None:
        artifact = artifact_rows_by_role[artifact_role]
        if (
            str(reference.get("path") or "")
            != str(artifact.get("path") or "")
            or str(reference.get("sha256") or "")
            != str(artifact.get("sha256") or "")
        ):
            raise RuntimeError(
                "Metadata freshness artifact lineage mismatch: "
                f"{artifact_role}"
            )

    assert_reference(
        {
            "path": registry_manifest.get("registry_path"),
            "sha256": registry_manifest.get("registry_sha256"),
        },
        artifact_role="source_registry",
    )
    normalized_manifest = json.loads(
        artifacts_by_role["normalized_manifest"].read_text(
            encoding="utf-8"
        )
    )
    assert_reference(
        _manifest_input(normalized_manifest, role="source_registry"),
        artifact_role="source_registry",
    )
    chunk_manifest = json.loads(
        artifacts_by_role["chunk_corpus_manifest"].read_text(
            encoding="utf-8"
        )
    )
    assert_reference(
        _manifest_input(chunk_manifest, role="normalized_manifest"),
        artifact_role="normalized_manifest",
    )
    assert_reference(
        _manifest_input(chunk_manifest, role="normalized_documents"),
        artifact_role="documents",
    )
    bm25_manifest = json.loads(
        artifacts_by_role["bm25_manifest"].read_text(encoding="utf-8")
    )
    for input_role, artifact_role in (
        ("chunk_v3", "chunks"),
        ("chunk_corpus_manifest", "chunk_corpus_manifest"),
        ("document_v3", "documents"),
    ):
        assert_reference(
            _manifest_input(bm25_manifest, role=input_role),
            artifact_role=artifact_role,
        )
    dense_manifest = json.loads(
        artifacts_by_role["dense_manifest"].read_text(
            encoding="utf-8"
        )
    )
    for input_role, artifact_role in (
        ("chunk_v3", "chunks"),
        ("chunk_corpus_manifest", "chunk_corpus_manifest"),
        ("document_v3", "documents"),
        ("bm25_manifest", "bm25_manifest"),
    ):
        assert_reference(
            _manifest_input(dense_manifest, role=input_role),
            artifact_role=artifact_role,
        )

    for source_id, coverage in source_coverage.items():
        if not isinstance(coverage, dict):
            raise RuntimeError(
                f"Invalid source coverage: {source_id}"
            )
        coverage_as_of = _validated_date(
            coverage.get("coverage_as_of"),
            field=f"{source_id}.coverage_as_of",
        )
        if coverage_as_of > registry_as_of:
            raise RuntimeError(
                f"Source coverage exceeds registry: {source_id}"
            )
        if str(coverage.get("status") or "") != registry_runs.get(
            source_id
        ):
            raise RuntimeError(
                f"Source coverage status differs from registry: {source_id}"
            )
    return snapshot


def resolve_metadata_freshness(
    *,
    source_id: str,
    requested_as_of: str,
    snapshot: dict[str, Any],
) -> MetadataFreshness:
    requested = _validated_date(
        requested_as_of,
        field="requested_as_of",
    )
    coverage = snapshot.get("source_coverage", {}).get(source_id)
    if not isinstance(coverage, dict):
        return MetadataFreshness(
            source_id=source_id,
            requested_as_of=requested,
            coverage_as_of=None,
            effective_as_of=None,
            source_status=None,
            status="unavailable",
        )
    source_status = str(coverage.get("status") or "")
    if source_status != "complete":
        return MetadataFreshness(
            source_id=source_id,
            requested_as_of=requested,
            coverage_as_of=None,
            effective_as_of=None,
            source_status=source_status or None,
            status="unavailable",
        )
    coverage_as_of = _validated_date(
        coverage.get("coverage_as_of"),
        field=f"{source_id}.coverage_as_of",
    )
    if requested <= coverage_as_of:
        return MetadataFreshness(
            source_id=source_id,
            requested_as_of=requested,
            coverage_as_of=coverage_as_of,
            effective_as_of=requested,
            source_status=source_status,
            status="verified_to_requested",
        )
    return MetadataFreshness(
        source_id=source_id,
        requested_as_of=requested,
        coverage_as_of=coverage_as_of,
        effective_as_of=coverage_as_of,
        source_status=source_status,
        status="bounded_to_snapshot",
    )


def _normalized(value: str) -> str:
    return " ".join(str(value or "").split())


def _collection_for(compact: str) -> dict[str, Any] | None:
    matches = [
        collection
        for collection in _COLLECTIONS
        if any(
            alias.replace(" ", "") in compact
            for alias in collection["aliases"]
        )
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _high_confidence_collection_list_command(
    question: str,
    *,
    aliases: tuple[str, ...],
) -> bool:
    compact = re.sub(r"\s+", "", _normalized(question))
    if not any(
        cue.replace(" ", "") in compact for cue in _LIST_CUES
    ):
        return False
    alias_pattern = "|".join(
        re.escape(alias.replace(" ", ""))
        for alias in sorted(aliases, key=len, reverse=True)
    )
    pattern = re.compile(
        rf"(?:현재|지금|수집된|수집한|공식)?"
        rf"(?:전체|모든)?"
        rf"(?:{alias_pattern})"
        rf"(?:은|는|이|가|을|를)?"
        rf"(?:(?:전체|전부|모두)(?:목록|리스트)?|목록|리스트)?"
        rf"(?:은|는|이|가|을|를)?"
        rf"(?:알려줘|알려주세요|보여줘|보여주세요|나열해줘|"
        rf"나열해주세요|정리해줘|정리해주세요|말해줘|말해주세요|"
        rf"뭐야|무엇이야)?"
        rf"[?？.!]*"
    )
    return pattern.fullmatch(compact) is not None


def plan_metadata_query(
    question: str,
    *,
    as_of: str,
) -> MetadataQueryPlan | None:
    """Plan high-confidence collection operations from a small registry.

    Document content questions deliberately fall through to the existing RAG.
    """

    normalized = _normalized(question)
    compact = re.sub(r"\s+", "", normalized)
    collection = _collection_for(compact)
    if collection is None:
        return None
    if any(cue.replace(" ", "") in compact for cue in _CONTENT_CUES):
        return None

    source_id = str(collection["source_id"])
    active_only = any(
        cue.replace(" ", "") in compact for cue in _ACTIVE_CUES
    )
    count_requested = any(
        cue.replace(" ", "") in compact for cue in _COUNT_CUES
    )
    latest_start = any(
        cue.replace(" ", "") in compact
        for cue in _LATEST_START_CUES
    )
    ambiguous_latest = any(
        cue.replace(" ", "") in compact
        for cue in _AMBIGUOUS_LATEST_CUES
    )
    latest_published = any(
        cue.replace(" ", "") in compact
        for cue in _LATEST_PUBLISHED_CUES
    )
    all_requested = any(
        cue.replace(" ", "") in compact for cue in _ALL_CUES
    )
    list_requested = any(
        cue.replace(" ", "") in compact for cue in _LIST_CUES
    )

    if active_only and source_id != "dnf_event":
        return None

    if latest_start and source_id == "dnf_event":
        return MetadataQueryPlan(
            mode="metadata",
            source_id=source_id,
            operation="latest",
            as_of=as_of,
            active_only=active_only,
            sort_field="valid_from",
        )
    if ambiguous_latest and source_id == "dnf_event" and not latest_published:
        return MetadataQueryPlan(
            mode="clarification",
            source_id=source_id,
            operation=None,
            as_of=as_of,
            active_only=active_only,
            sort_field=None,
            clarification=(
                "최근 등록된 이벤트와 최근 시작한 이벤트 중 "
                "어떤 기준으로 찾을까요?"
            ),
        )
    if ambiguous_latest or latest_published:
        return MetadataQueryPlan(
            mode="metadata",
            source_id=source_id,
            operation="latest",
            as_of=as_of,
            active_only=active_only,
            sort_field=str(collection["latest_sort_field"]),
        )
    if count_requested:
        if source_id == "dnf_event" and not active_only and not all_requested:
            return MetadataQueryPlan(
                mode="clarification",
                source_id=source_id,
                operation=None,
                as_of=as_of,
                active_only=False,
                sort_field=None,
                clarification=(
                    "현재 진행 중인 이벤트 개수와 전체 수집 이벤트 "
                    "개수 중 어느 쪽을 찾을까요?"
                ),
            )
        return MetadataQueryPlan(
            mode="metadata",
            source_id=source_id,
            operation="count",
            as_of=as_of,
            active_only=active_only,
            sort_field=None,
        )
    if active_only:
        return MetadataQueryPlan(
            mode="metadata",
            source_id=source_id,
            operation="list_all",
            as_of=as_of,
            active_only=True,
            sort_field="valid_from",
        )
    if list_requested:
        if not _high_confidence_collection_list_command(
            normalized,
            aliases=tuple(collection["aliases"]),
        ):
            return None
        return MetadataQueryPlan(
            mode="metadata",
            source_id=source_id,
            operation="list_all",
            as_of=as_of,
            active_only=False,
            sort_field=None,
        )
    return None


def plan_event_metadata_query(
    question: str,
    *,
    as_of: str,
) -> MetadataQueryPlan | None:
    """Backward-compatible alias for the registry planner."""

    plan = plan_metadata_query(question, as_of=as_of)
    if plan is None or plan.source_id != "dnf_event":
        return None
    return plan


def _active_at(document: dict[str, Any], as_of: str) -> bool:
    valid_from = str(document.get("valid_from") or "")
    valid_to = str(document.get("valid_to") or "")
    if not valid_from:
        return False
    return valid_from <= as_of and (not valid_to or as_of <= valid_to)


def execute_metadata_query(
    plan: MetadataQueryPlan,
    *,
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if plan.mode != "metadata" or plan.operation is None:
        raise RuntimeError("Only executable metadata plans can be run")

    unique: dict[str, dict[str, Any]] = {}
    for document in documents:
        if document.get("source_id") != plan.source_id:
            continue
        if not document.get("default_exposure"):
            continue
        if document.get("review_required"):
            continue
        document_id = str(document.get("document_id") or "")
        if not document_id:
            continue
        if plan.active_only and not _active_at(document, plan.as_of):
            continue
        if plan.operation == "latest":
            assert plan.sort_field is not None
            sort_value = str(document.get(plan.sort_field) or "")
            if not sort_value or sort_value > plan.as_of:
                continue
        unique[document_id] = document

    rows = list(unique.values())
    if plan.operation == "latest":
        assert plan.sort_field is not None
        rows = [row for row in rows if row.get(plan.sort_field)]
        if not rows:
            return []
        latest_value = max(str(row[plan.sort_field]) for row in rows)
        rows = [
            row
            for row in rows
            if str(row.get(plan.sort_field) or "") == latest_value
        ]

    return sorted(
        rows,
        key=lambda row: (
            str(row.get(plan.sort_field or "valid_from") or ""),
            str(row.get("published_at") or ""),
            str(row.get("title") or ""),
        ),
        reverse=True,
    )


def render_metadata_query_result(
    *,
    question: str,
    plan: MetadataQueryPlan,
    documents: list[dict[str, Any]],
    started: float,
    freshness: MetadataFreshness | None = None,
) -> dict[str, Any]:
    collection = _COLLECTION_BY_SOURCE.get(plan.source_id)
    if collection is None:
        raise RuntimeError(
            f"Unsupported metadata source: {plan.source_id}"
        )
    collection_label = str(collection["label"])
    subject_label = (
        "진행 중인 이벤트"
        if plan.active_only and plan.source_id == "dnf_event"
        else f"{collection_label} 문서"
    )
    freshness = freshness or MetadataFreshness(
        source_id=plan.source_id,
        requested_as_of=plan.as_of,
        coverage_as_of=plan.as_of,
        effective_as_of=plan.as_of,
        source_status="complete",
        status="verified_to_requested",
    )
    if plan.mode == "clarification":
        return {
            "metadata_query_version": METADATA_QUERY_VERSION,
            "question": question,
            "response_mode": "clarification",
            "rendered_answer": plan.clarification or "",
            "requirements": [],
            "live_claimspec": [asdict(plan)],
            "route": {
                "route_action": "clarify",
                "query_mode": "metadata",
                "source_ids": [plan.source_id],
            },
            "candidates": [],
            "verification": {
                "all_exposed_citations_verified": True,
                "metadata_query_plan_validated": True,
                "qwen_called": False,
            },
            "latency": {
                "retrieval_ms": 0.0,
                "metadata_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "planner_ms": 0.0,
                "generation_ms": 0.0,
                "total_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
            },
        }

    if freshness.status == "unavailable":
        metadata_ms = round(
            (time.perf_counter() - started) * 1000,
            3,
        )
        return {
            "metadata_query_version": METADATA_QUERY_VERSION,
            "question": question,
            "response_mode": "abstain",
            "rendered_answer": (
                "공식 문서 스냅샷의 최신성 상태를 확인할 수 없어 "
                "현재·최신 결과를 제공하지 않습니다."
            ),
            "requirements": [],
            "live_claimspec": [asdict(plan)],
            "route": {
                "route_action": "metadata_query",
                "query_mode": "metadata",
                "source_ids": [plan.source_id],
                "requested_as_of": freshness.requested_as_of,
                "operation": plan.operation,
            },
            "candidates": [],
            "verification": {
                "all_exposed_citations_verified": True,
                "metadata_query_plan_validated": True,
                "freshness_status": freshness.status,
                "requested_as_of": freshness.requested_as_of,
                "coverage_as_of": freshness.coverage_as_of,
                "effective_as_of": freshness.effective_as_of,
                "qwen_called": False,
            },
            "latency": {
                "retrieval_ms": 0.0,
                "metadata_ms": metadata_ms,
                "planner_ms": 0.0,
                "generation_ms": 0.0,
                "total_ms": metadata_ms,
            },
        }
    if plan.as_of != freshness.effective_as_of:
        raise RuntimeError(
            "Metadata plan date differs from freshness boundary"
        )

    rows = execute_metadata_query(plan, documents=documents)
    citations = [
        {
            "document_id": row["document_id"],
            "source_id": row["source_id"],
            "title": row.get("title"),
            "published_at": row.get("published_at"),
            "valid_from": row.get("valid_from"),
            "valid_to": row.get("valid_to"),
            "canonical_url": row.get("canonical_url"),
            "field_refs": [
                "title",
                *(
                    [plan.sort_field]
                    if plan.sort_field is not None
                    else ["valid_from", "valid_to"]
                ),
            ],
            "evidence_ref": f"META{index}",
        }
        for index, row in enumerate(rows, 1)
    ]
    if plan.operation == "count":
        answer = f"{plan.as_of} 기준 {subject_label}는 {len(rows)}개입니다."
        rendered_answer = answer
    else:
        if plan.operation == "latest":
            latest_relation = (
                "가장 최근 시작한"
                if plan.sort_field == "valid_from"
                else "가장 최근 게시된"
            )
            heading = (
                f"{plan.as_of} 기준 {latest_relation} "
                f"{collection_label}"
            )
        else:
            heading = (
                f"{plan.as_of} 기준 {subject_label} {len(rows)}개"
            )
        lines = [heading]
        for index, row in enumerate(rows, 1):
            if plan.source_id == "dnf_event":
                metadata_text = " ~ ".join(
                    value
                    for value in (
                        str(row.get("valid_from") or ""),
                        str(row.get("valid_to") or ""),
                    )
                    if value
                )
            else:
                metadata_text = str(row.get("published_at") or "")
            lines.append(
                f"{index}. {row.get('title')}"
                + (
                    f" — {metadata_text}"
                    if metadata_text
                    else ""
                )
                + f" [근거 {index}]"
            )
        rendered_answer = "\n".join(lines)
        answer = "\n".join(str(row.get("title") or "") for row in rows)

    if freshness.status == "bounded_to_snapshot":
        rendered_answer = (
            f"공식 문서를 {freshness.coverage_as_of}까지 "
            "수집·검증된 범위의 결과입니다. "
            f"{freshness.requested_as_of} 현재 상태는 보장하지 않습니다.\n"
            f"{rendered_answer}"
        )

    metadata_ms = round(
        (time.perf_counter() - started) * 1000,
        3,
    )
    has_result = bool(rows) or plan.operation == "count"
    response_mode = (
        "partial"
        if has_result and freshness.status == "bounded_to_snapshot"
        else "full_answer"
        if has_result
        else "abstain"
    )
    return {
        "metadata_query_version": METADATA_QUERY_VERSION,
        "question": question,
        "response_mode": response_mode,
        "rendered_answer": rendered_answer if has_result else "",
        "requirements": [
            {
                "requirement_id": "metadata_1",
                "subject": subject_label,
                "relation": plan.operation,
                "value_type": "number" if plan.operation == "count" else "entity_list",
                "status": "supported_exact" if rows or plan.operation == "count" else "unsupported",
                "value": len(rows) if plan.operation == "count" else [
                    row.get("title") for row in rows
                ],
                "answer": answer if rows or plan.operation == "count" else "",
                "citations": citations,
                "verification": {
                    "failure_reasons": [],
                    "metadata_fields_verified": True,
                    "qwen_called": False,
                },
            }
        ],
        "live_claimspec": [
            {
                "requirement_id": "metadata_1",
                "subject": subject_label,
                "relation": str(plan.operation or ""),
                "value_type": (
                    "number"
                    if plan.operation == "count"
                    else "entity_list"
                ),
                "cardinality": (
                    "all"
                    if plan.operation == "list_all"
                    else "single"
                ),
            }
        ],
        "route": {
            "route_action": "metadata_query",
            "query_mode": "metadata",
            "source_ids": [plan.source_id],
            "as_of": plan.as_of,
            "requested_as_of": freshness.requested_as_of,
            "coverage_as_of": freshness.coverage_as_of,
            "effective_as_of": freshness.effective_as_of,
            "operation": plan.operation,
        },
        "candidates": [
            {
                "candidate_ref": str(index),
                "document_id": row["document_id"],
                "source_id": row["source_id"],
                "title": row.get("title"),
                "published_at": row.get("published_at"),
                "status": row.get("status"),
                "valid_from": row.get("valid_from"),
                "valid_to": row.get("valid_to"),
                "canonical_url": row.get("canonical_url"),
            }
            for index, row in enumerate(rows, 1)
        ],
        "verification": {
            "all_exposed_citations_verified": True,
            "metadata_query_plan_validated": True,
            "document_count": len(rows),
            "freshness_status": freshness.status,
            "requested_as_of": freshness.requested_as_of,
            "coverage_as_of": freshness.coverage_as_of,
            "effective_as_of": freshness.effective_as_of,
            "qwen_called": False,
        },
        "latency": {
            "retrieval_ms": 0.0,
            "metadata_ms": metadata_ms,
            "planner_ms": 0.0,
            "generation_ms": 0.0,
            "total_ms": metadata_ms,
        },
    }
