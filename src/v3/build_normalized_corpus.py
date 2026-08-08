from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import canonicalize_url, file_sha256, stable_content_hash
from src.v3.collect_details import (
    _canonical_json_bytes,
    _serialize_jsonl,
    normalize_block,
    normalize_space,
    parse_fixed_timestamp,
    write_immutable,
)
from src.v3.schemas import (
    DOCUMENT_CONTENT_SCHEMA_VERSION,
    NORMALIZED_CORPUS_MANIFEST_SCHEMA_VERSION,
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    VALID_DOCUMENT_STATUSES,
)


BUILDER_VERSION = "dnf_normalized_corpus_builder_v3.2"
CONTENT_HASH_VERSION = "dnf_normalized_content_hash_v3.1"

DEFAULT_REGISTRY = Path(
    "data/v3/discovery/"
    "source_registry_04c902454e96e279edeacd12d56e25dddcd5523d98f65fd4444ea981559dec3a.jsonl"
)
DEFAULT_LEDGER = Path(
    "data/v3/collections/"
    "detail_full_collection_ledger_0165b356041a60ca920949b9d8c4436cb7509bdf7787fe97fee90fb9856ce12b.jsonl"
)
DEFAULT_HARDENED_PREVIEW = Path(
    "data/v3/collections/"
    "detail_hardened_extraction_preview_ac49a188c07ec22cc3265ebfa656f4849bfad3f5070779f538925e920fc4c4c8.jsonl"
)
DEFAULT_VISUAL_EVIDENCE = Path(
    "data/v3/visual_evidence/"
    "visual_document_evidence_c7362de31d59ee1f0877477caa8c5d4848fdbdf40719b5c64cdb861c29469d38.jsonl"
)
DEFAULT_CORRECTION_OVERLAY = Path(
    "data/v3/visual_evidence/"
    "discovery_correction_overlay_0841fdad1f8c80dcda51036162b524ed4c7cf3cd31fb2bdb26a915cf77ddf61b.jsonl"
)
DEFAULT_VISUAL_MANIFEST = Path(
    "data/v3/visual_evidence/"
    "visual_evidence_manifest_ff585eb897627edd9bceae3f643fe5ac23904a07fcbed7b5fbe51cb59e64050b.json"
)
DEFAULT_BASELINE_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_v3.0_c77299d729a6.jsonl"
)
DEFAULT_NORMALIZED_DIR = Path("data/v3/normalized")
DEFAULT_REPORT_DIR = Path("reports/v3")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text_hash(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _nullable(value: Any) -> str | None:
    normalized = normalize_space(value)
    return normalized or None


def _unique_by_url(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = canonicalize_url(row.get("canonical_url"))
        if url in result:
            raise RuntimeError(f"Duplicate canonical URL in {label}: {url}")
        result[url] = row
    return result


def _category_path(registry: dict[str, Any]) -> list[str]:
    values = [normalize_space(registry.get("source_kind"))]
    category = normalize_space(registry.get("category"))
    if category and category.lower() != "unknown" and category not in values:
        values.append(category)
    return values or ["unknown"]


def _lineage_key(registry: dict[str, Any]) -> str:
    if registry["source_id"] == "dnf_account_policy":
        return f"{registry['source_id']}\n{canonicalize_url(registry['listing_url'])}"
    return canonicalize_url(registry["canonical_url"])


def _lineage_id(registry: dict[str, Any]) -> str:
    return f"lineage_sha256_{_sha256_bytes(_lineage_key(registry).encode('utf-8'))}"


def _content_hash(
    *,
    title: str,
    source_kind: str,
    category_path: list[str],
    published_at: str | None,
    valid_from: str | None,
    valid_to: str | None,
    text: str,
    visual_text_hash: str | None,
) -> str:
    payload = {
        "content_hash_version": CONTENT_HASH_VERSION,
        "title": title,
        "source_kind": source_kind,
        "category_path": category_path,
        "published_at": published_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "text": text,
        "visual_text_hash": visual_text_hash,
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _identity(canonical_url: str, content_hash: str) -> str:
    return _sha256_bytes(f"{canonical_url}\n{content_hash}".encode("utf-8"))


def _effective_default_exposure(source_kind: str, status: str, requested: Any) -> bool:
    return bool(requested) and status in {"current", "upcoming"} and source_kind not in {
        "preview_patch",
        "roadmap_statement",
    }


def _visual_payload(
    visual: dict[str, Any] | None,
    visual_evidence_path: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    if visual is None:
        return None, None
    if not visual["normalization_eligible_after_visual"]:
        raise RuntimeError(
            f"Visual evidence is not normalization eligible: {visual['canonical_url']}"
        )
    text = normalize_block(visual.get("ocr_text", ""))
    if not text:
        raise RuntimeError(f"Visual evidence has empty OCR text: {visual['canonical_url']}")
    text_hash = _text_hash(text)
    return (
        {
            "evidence_artifact_path": visual_evidence_path.as_posix(),
            "evidence_artifact_sha256": file_sha256(visual_evidence_path),
            "visual_version": visual["visual_version"],
            "status": visual["visual_evidence_status"],
            "text": text,
            "text_hash": text_hash,
            "unverified_ocr": True,
            "asset_count": visual["asset_count"],
            "asset_fetch_failed": visual["asset_fetch_failed"],
            "tolerated_css_404_asset_urls": visual["tolerated_css_404_asset_urls"],
        },
        text_hash,
    )


def _new_document_pair(
    *,
    registry: dict[str, Any],
    ledger: dict[str, Any],
    preview: dict[str, Any],
    visual: dict[str, Any] | None,
    visual_evidence_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical_url = canonicalize_url(registry["canonical_url"])
    if canonical_url != canonicalize_url(ledger["canonical_url"]):
        raise RuntimeError(f"Registry/ledger URL mismatch: {canonical_url}")
    if canonical_url != canonicalize_url(preview["canonical_url"]):
        raise RuntimeError(f"Registry/preview URL mismatch: {canonical_url}")
    raw_path = Path(preview["raw_snapshot_path"])
    raw_content_hash = preview["raw_content_hash"]
    if ledger["content_hash"] != raw_content_hash:
        raise RuntimeError(f"Ledger/preview raw hash mismatch: {canonical_url}")
    if file_sha256(raw_path) != raw_content_hash:
        raise RuntimeError(f"Raw snapshot hash mismatch: {raw_path}")
    if preview["content_status"] != "parsed":
        raise RuntimeError(f"Candidate detail is not parsed: {canonical_url}")

    title = normalize_space(preview["title"])
    text = normalize_block(preview["extracted_text"])
    if not title or not text:
        raise RuntimeError(f"Candidate has empty title/text: {canonical_url}")
    source_kind = normalize_space(registry["source_kind"])
    categories = _category_path(registry)
    published_at = _nullable(preview.get("published_at") or registry.get("published_at"))
    valid_from = _nullable(preview.get("valid_from") or registry.get("period_start"))
    valid_to = _nullable(preview.get("valid_to") or registry.get("period_end"))
    visual_payload, visual_text_hash = _visual_payload(visual, visual_evidence_path)
    normalized_text_hash = _text_hash(text)
    content_hash = _content_hash(
        title=title,
        source_kind=source_kind,
        category_path=categories,
        published_at=published_at,
        valid_from=valid_from,
        valid_to=valid_to,
        text=text,
        visual_text_hash=visual_text_hash,
    )
    identity = _identity(canonical_url, content_hash)
    status = normalize_space(registry["status"])
    if status not in VALID_DOCUMENT_STATUSES:
        raise RuntimeError(f"Invalid registry status for {canonical_url}: {status}")
    warnings = sorted(set(preview.get("extraction_warnings") or []))
    if visual_payload is not None:
        warnings.append("visual_ocr_unverified_supplement")
    document = {
        "document_schema_version": NORMALIZED_DOCUMENT_SCHEMA_VERSION,
        "document_id": f"document_sha256_{identity}",
        "source_snapshot_id": f"snapshot_sha256_{raw_content_hash}",
        "source_id": registry["source_id"],
        "listing_url": canonicalize_url(registry["listing_url"]),
        "canonical_url": canonical_url,
        "canonical_url_kind": registry["canonical_url_kind"],
        "source_kind": source_kind,
        "authority": "official",
        "title": title,
        "category_path": categories,
        "published_at": published_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "lineage_id": _lineage_id(registry),
        "revision_id": f"revision_sha256_{identity}",
        "supersedes_document_id": None,
        "status": status,
        "default_exposure": _effective_default_exposure(
            source_kind, status, registry["default_exposure"]
        ),
        "content_hash": content_hash,
        "raw_content_hash": raw_content_hash,
        "normalized_text_hash": normalized_text_hash,
        "visual_text_hash": visual_text_hash,
        "fetched_at": ledger["fetched_at"],
        "parser_version": preview["parser_version"],
        "raw_source_path": raw_path.as_posix(),
    }
    content = {
        "content_schema_version": DOCUMENT_CONTENT_SCHEMA_VERSION,
        "document_id": document["document_id"],
        "canonical_url": canonical_url,
        "content_hash": content_hash,
        "text": text,
        "text_hash": normalized_text_hash,
        "text_source": "hardened_dom",
        "parser_version": preview["parser_version"],
        "raw_content_hash": raw_content_hash,
        "raw_source_path": raw_path.as_posix(),
        "extraction_warnings": sorted(set(warnings)),
        "extraction_metadata": {
            "content_selector": preview["content_selector"],
            "heading_count": preview["heading_count"],
            "table_count": preview["table_count"],
            "image_count": preview["image_count"],
            "image_dependency_risk": preview["image_dependency_risk"],
            "title_validation_status": preview["title_validation_status"],
            "faq_locator_validated": preview["faq_locator_validated"],
            "policy_revision_validated": preview["policy_revision_validated"],
        },
        "visual_evidence": visual_payload,
    }
    return document, content


def _find_baseline_content(
    baseline_document: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    raw_path = Path(baseline_document["raw_source_path"])
    for row in read_jsonl(raw_path):
        if canonicalize_url(row.get("source_url")) != baseline_document["canonical_url"]:
            continue
        if stable_content_hash(row) != baseline_document["content_hash"]:
            raise RuntimeError(
                f"Baseline content hash mismatch: {baseline_document['canonical_url']}"
            )
        return row, raw_path
    raise RuntimeError(f"Baseline raw row not found: {baseline_document['canonical_url']}")


def _preserved_baseline_pair(
    baseline_document: dict[str, Any],
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    raw_row, raw_path = _find_baseline_content(baseline_document)
    text = normalize_block(raw_row.get("text", ""))
    if not text:
        raise RuntimeError(f"Baseline revision has empty text: {baseline_document['canonical_url']}")
    document = dict(baseline_document)
    document.update(
        document_schema_version=NORMALIZED_DOCUMENT_SCHEMA_VERSION,
        source_id=registry["source_id"],
        listing_url=canonicalize_url(registry["listing_url"]),
        canonical_url_kind=registry["canonical_url_kind"],
        lineage_id=_lineage_id(registry),
        status="superseded",
        default_exposure=False,
        raw_content_hash=file_sha256(raw_path),
        normalized_text_hash=_text_hash(text),
        visual_text_hash=None,
    )
    content = {
        "content_schema_version": DOCUMENT_CONTENT_SCHEMA_VERSION,
        "document_id": document["document_id"],
        "canonical_url": document["canonical_url"],
        "content_hash": document["content_hash"],
        "text": text,
        "text_hash": document["normalized_text_hash"],
        "text_source": "legacy_v2_normalized_text",
        "parser_version": document["parser_version"],
        "raw_content_hash": document["raw_content_hash"],
        "raw_source_path": raw_path.as_posix(),
        "extraction_warnings": ["preserved_material_baseline_revision"],
        "extraction_metadata": {"baseline_document_artifact": True},
        "visual_evidence": None,
    }
    return document, content, raw_path


def _revision_order(document: dict[str, Any]) -> tuple[str, str, str]:
    return (
        document.get("valid_from") or document.get("published_at") or "",
        document["fetched_at"],
        document["document_id"],
    )


def _link_revisions(documents: list[dict[str, Any]]) -> None:
    by_lineage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        by_lineage[document["lineage_id"]].append(document)
    for revisions in by_lineage.values():
        revisions.sort(key=_revision_order)
        previous_id: str | None = None
        for index, document in enumerate(revisions):
            document["supersedes_document_id"] = previous_id
            if index < len(revisions) - 1:
                document["status"] = "superseded"
                document["default_exposure"] = False
            previous_id = document["document_id"]


def _manifest_input(role: str, path: Path, row_count: int | None) -> dict[str, Any]:
    return {
        "role": role,
        "path": path.as_posix(),
        "sha256": file_sha256(path),
        "row_count": row_count,
    }


def _render_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DNF RAG v3 revision-aware DocumentV3 승격 보고서",
        "",
        f"- builder: `{report['builder_version']}`",
        f"- built_at: `{report['built_at']}`",
        f"- manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## 결과",
        "",
        "| candidates | preserved revisions | documents | contents | excluded | default exposure |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary['candidate_documents']} | {summary['preserved_baseline_revisions']} | "
            f"{summary['document_rows']} | {summary['content_rows']} | "
            f"{summary['excluded_documents']} | {summary['default_exposure_documents']} |"
        ),
        "",
        "## 출처별 문서",
        "",
        "| source | rows | default exposure |",
        "|---|---:|---:|",
    ]
    for source_id, values in report["by_source"].items():
        lines.append(
            f"| `{source_id}` | {values['documents']} | {values['default_exposure']} |"
        )
    lines.extend(
        [
            "",
            "## 게이트",
            "",
            *[f"- {key}: `{value}`" for key, value in report["gates"].items()],
            "",
            f"DocumentV3 promotion: **{report['promotion_decision']}**",
            "",
            "OCR text는 DOM text와 분리된 비검수 보조 evidence로 보존했다. ChunkV3, 검색, 구조화 store, 학습은 실행하지 않았다.",
            "",
        ]
    )
    return "\n".join(lines)


def build_normalized_corpus(
    *,
    built_at: str,
    registry_path: Path,
    ledger_path: Path,
    hardened_preview_path: Path,
    visual_evidence_path: Path,
    correction_overlay_path: Path,
    visual_manifest_path: Path,
    baseline_documents_path: Path,
    normalized_dir: Path,
    report_dir: Path,
    corpus_name: str = "dnf_official_detail",
) -> dict[str, Any]:
    parse_fixed_timestamp(built_at)
    explicit_paths = [
        registry_path,
        ledger_path,
        hardened_preview_path,
        visual_evidence_path,
        correction_overlay_path,
        visual_manifest_path,
        baseline_documents_path,
    ]
    for path in explicit_paths:
        if not path.is_file():
            raise RuntimeError(f"Required input does not exist: {path}")
    input_hashes_before = {path: file_sha256(path) for path in explicit_paths}

    registry_rows = read_jsonl(registry_path)
    ledger_rows = read_jsonl(ledger_path)
    preview_rows = read_jsonl(hardened_preview_path)
    visual_rows = read_jsonl(visual_evidence_path)
    overlay_rows = read_jsonl(correction_overlay_path)
    baseline_rows = read_jsonl(baseline_documents_path)
    registry = _unique_by_url(registry_rows, "registry")
    ledger = _unique_by_url(ledger_rows, "ledger")
    previews = _unique_by_url(preview_rows, "hardened preview")
    visuals = _unique_by_url(visual_rows, "visual evidence")
    overlays = _unique_by_url(overlay_rows, "correction overlay")
    baseline = _unique_by_url(baseline_rows, "baseline DocumentV3")

    eligible_urls = {
        url for url, row in registry.items() if row["eligible_for_collection"]
    }
    if set(ledger) != eligible_urls or set(previews) != eligible_urls:
        raise RuntimeError("Eligible registry, ledger, and hardened preview URL sets differ")

    excluded: list[dict[str, Any]] = []
    candidate_urls: list[str] = []
    for url in sorted(eligible_urls):
        if url in overlays:
            overlay = overlays[url]
            if overlay["normalization_eligible"]:
                raise RuntimeError(f"Correction overlay unexpectedly eligible: {url}")
            excluded.append(
                {
                    "canonical_url": url,
                    "source_id": registry[url]["source_id"],
                    "reason": overlay["correction_reason"],
                    "effective_status": overlay["effective_status"],
                    "effective_default_exposure": overlay["effective_default_exposure"],
                }
            )
            continue
        preview = previews[url]
        visual = visuals.get(url)
        if preview["normalization_eligible"] or (
            visual and visual["normalization_eligible_after_visual"]
        ):
            candidate_urls.append(url)
        else:
            raise RuntimeError(f"Eligible URL has no normalization path or overlay: {url}")

    documents: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    for url in candidate_urls:
        document, content = _new_document_pair(
            registry=registry[url],
            ledger=ledger[url],
            preview=previews[url],
            visual=visuals.get(url),
            visual_evidence_path=visual_evidence_path,
        )
        documents.append(document)
        contents.append(content)

    preserved_raw_paths: set[Path] = set()
    preserved_count = 0
    preserved_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for url in candidate_urls:
        if previews[url].get("guide_change_classification") != "official_revision_after_baseline":
            continue
        baseline_document = baseline.get(url)
        if baseline_document is None:
            raise RuntimeError(f"Material guide revision lacks baseline DocumentV3: {url}")
        raw_path = Path(baseline_document["raw_source_path"])
        input_hashes_before[raw_path] = file_sha256(raw_path)
        preserved_raw_paths.add(raw_path)
        preserved_candidates.append((baseline_document, registry[url]))

    for baseline_document, registry_row in preserved_candidates:
        document, content, raw_path = _preserved_baseline_pair(
            baseline_document, registry_row
        )
        documents.append(document)
        contents.append(content)
        preserved_count += 1

    _link_revisions(documents)
    documents.sort(key=lambda row: (row["source_id"], row["canonical_url"], _revision_order(row)))
    content_by_id = {row["document_id"]: row for row in contents}
    if len(content_by_id) != len(contents):
        raise RuntimeError("Duplicate document_id in content rows")
    contents = [content_by_id[row["document_id"]] for row in documents]

    document_ids = {row["document_id"] for row in documents}
    if len(document_ids) != len(documents):
        raise RuntimeError("Duplicate document_id in normalized documents")
    if document_ids != set(content_by_id):
        raise RuntimeError("Document/content ID sets differ")
    for document in documents:
        content = content_by_id[document["document_id"]]
        if document["normalized_text_hash"] != content["text_hash"]:
            raise RuntimeError(f"Document/content text hash mismatch: {document['document_id']}")
        if document["content_hash"] != content["content_hash"]:
            raise RuntimeError(f"Document/content content hash mismatch: {document['document_id']}")

    document_bytes = _serialize_jsonl(
        documents, lambda row: (row["source_id"], row["canonical_url"], row["fetched_at"], row["document_id"])
    )
    document_sha256 = _sha256_bytes(document_bytes)
    document_path = normalized_dir / f"documents_{corpus_name}_v3.1_{document_sha256}.jsonl"
    write_immutable(document_path, document_bytes)
    content_bytes = _serialize_jsonl(
        contents, lambda row: row["document_id"]
    )
    content_sha256 = _sha256_bytes(content_bytes)
    content_path = normalized_dir / f"document_contents_{corpus_name}_v3.1_{content_sha256}.jsonl"
    write_immutable(content_path, content_bytes)

    input_rows = [
        _manifest_input("source_registry", registry_path, len(registry_rows)),
        _manifest_input("detail_collection_ledger", ledger_path, len(ledger_rows)),
        _manifest_input("hardened_preview", hardened_preview_path, len(preview_rows)),
        _manifest_input("visual_document_evidence", visual_evidence_path, len(visual_rows)),
        _manifest_input("correction_overlay", correction_overlay_path, len(overlay_rows)),
        _manifest_input("visual_evidence_manifest", visual_manifest_path, None),
        _manifest_input("baseline_document_v3", baseline_documents_path, len(baseline_rows)),
    ]
    for path in sorted(preserved_raw_paths, key=lambda value: value.as_posix()):
        input_rows.append(_manifest_input("preserved_baseline_raw_snapshot", path, len(read_jsonl(path))))
    input_rows.sort(key=lambda row: (row["role"], row["path"]))
    manifest_unsigned = {
        "manifest_schema_version": NORMALIZED_CORPUS_MANIFEST_SCHEMA_VERSION,
        "corpus_name": corpus_name,
        "builder_version": BUILDER_VERSION,
        "built_at": built_at,
        "inputs": input_rows,
        "documents": {
            "path": document_path.as_posix(),
            "sha256": document_sha256,
            "row_count": len(documents),
        },
        "contents": {
            "path": content_path.as_posix(),
            "sha256": content_sha256,
            "row_count": len(contents),
        },
        "candidate_document_count": len(candidate_urls),
        "preserved_baseline_revision_count": preserved_count,
        "excluded_documents": excluded,
    }
    manifest_id_hash = _sha256_bytes(_canonical_json_bytes(manifest_unsigned))
    manifest = dict(manifest_unsigned)
    manifest["manifest_id"] = f"manifest_sha256_{manifest_id_hash}"
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_path = normalized_dir / f"normalized_corpus_manifest_{manifest_sha256}.json"
    write_immutable(manifest_path, manifest_bytes)

    status_counts = Counter(row["status"] for row in documents)
    default_count = sum(row["default_exposure"] for row in documents)
    material_revision_count = sum(
        previews[url].get("guide_change_classification")
        == "official_revision_after_baseline"
        for url in candidate_urls
    )
    gates = {
        "all_eligible_urls_accounted_for": (
            len(candidate_urls) + len(excluded) == len(eligible_urls)
        ),
        "excluded_documents_are_overlay_backed": all(
            row["canonical_url"] in overlays
            and not overlays[row["canonical_url"]]["normalization_eligible"]
            for row in excluded
        ),
        "all_material_revisions_preserved": preserved_count == material_revision_count,
        "document_content_id_sets_match": document_ids == set(content_by_id),
        "empty_title_or_text": sum(
            not row["title"] or not content_by_id[row["document_id"]]["text"]
            for row in documents
        ),
        "invalid_status": sum(row["status"] not in VALID_DOCUMENT_STATUSES for row in documents),
        "default_exposure_policy_violations": sum(
            row["default_exposure"]
            and (
                row["status"] not in {"current", "upcoming"}
                or row["source_kind"] in {"preview_patch", "roadmap_statement"}
            )
            for row in documents
        ),
        "visual_ocr_has_separate_unverified_provenance": all(
            content["visual_evidence"] is None
            or (
                content["text_source"] == "hardened_dom"
                and content["visual_evidence"]["unverified_ocr"] is True
                and "visual_ocr_unverified_supplement" in content["extraction_warnings"]
            )
            for content in contents
        ),
        "raw_hash_mismatches": 0,
    }
    gate_go = all(
        value is True if isinstance(value, bool) else value == 0
        for value in gates.values()
    )
    by_source = {}
    for source_id in sorted({row["source_id"] for row in documents}):
        rows = [row for row in documents if row["source_id"] == source_id]
        by_source[source_id] = {
            "documents": len(rows),
            "default_exposure": sum(row["default_exposure"] for row in rows),
            "status": dict(sorted(Counter(row["status"] for row in rows).items())),
        }
    report = {
        "report_schema_version": "dnf_document_v3_promotion_report_v3.1",
        "builder_version": BUILDER_VERSION,
        "built_at": built_at,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "summary": {
            "candidate_documents": len(candidate_urls),
            "preserved_baseline_revisions": preserved_count,
            "document_rows": len(documents),
            "content_rows": len(contents),
            "excluded_documents": len(excluded),
            "default_exposure_documents": default_count,
            "visual_evidence_documents": sum(
                row["visual_evidence"] is not None for row in contents
            ),
            "status": dict(sorted(status_counts.items())),
        },
        "by_source": by_source,
        "excluded_documents": excluded,
        "gates": gates,
        "promotion_decision": "GO" if gate_go else "NO-GO",
    }
    report_bytes = _canonical_json_bytes(report, indent=2)
    report_sha256 = _sha256_bytes(report_bytes)
    report_json_path = report_dir / f"document_v3_promotion_{report_sha256}.json"
    report_markdown_path = report_dir / f"document_v3_promotion_{report_sha256}.md"
    write_immutable(report_json_path, report_bytes)
    write_immutable(report_markdown_path, _render_report(report).encode("utf-8"))

    for path, digest in input_hashes_before.items():
        if file_sha256(path) != digest:
            raise RuntimeError(f"Input changed while building normalized corpus: {path}")
    return {
        "document_path": document_path.as_posix(),
        "document_sha256": document_sha256,
        "content_path": content_path.as_posix(),
        "content_sha256": content_sha256,
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256,
        "report_json_path": report_json_path.as_posix(),
        "report_markdown_path": report_markdown_path.as_posix(),
        "report_sha256": report_sha256,
        "summary": report["summary"],
        "by_source": by_source,
        "promotion_decision": report["promotion_decision"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build revision-aware DocumentV3 and separately provenanced normalized content."
    )
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--hardened-preview", type=Path, default=DEFAULT_HARDENED_PREVIEW)
    parser.add_argument("--visual-evidence", type=Path, default=DEFAULT_VISUAL_EVIDENCE)
    parser.add_argument("--correction-overlay", type=Path, default=DEFAULT_CORRECTION_OVERLAY)
    parser.add_argument("--visual-manifest", type=Path, default=DEFAULT_VISUAL_MANIFEST)
    parser.add_argument("--baseline-documents", type=Path, default=DEFAULT_BASELINE_DOCUMENTS)
    parser.add_argument("--normalized-dir", type=Path, default=DEFAULT_NORMALIZED_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = build_normalized_corpus(
        built_at=args.built_at,
        registry_path=args.registry,
        ledger_path=args.ledger,
        hardened_preview_path=args.hardened_preview,
        visual_evidence_path=args.visual_evidence,
        correction_overlay_path=args.correction_overlay,
        visual_manifest_path=args.visual_manifest,
        baseline_documents_path=args.baseline_documents,
        normalized_dir=args.normalized_dir,
        report_dir=args.report_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
