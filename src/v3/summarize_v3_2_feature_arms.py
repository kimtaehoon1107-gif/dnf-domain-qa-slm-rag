from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable


SUMMARY_VERSION = "v3.2-feature-arm-summary-v2"
DEFAULT_OUTPUT_DIR = Path("data/v3/structured")
DEFAULT_REPORT_DIR = Path("reports/v3")
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)

REPORTS = {
    "table_atomic_facts": Path("reports/v3/table_atomic_facts_arm1_ab_14fc2d7d1ceab76f342923e4da5762912a3980923d07273a56ea17b2fc93bd80.json"),
    "evidence_clean_view": Path("reports/v3/evidence_clean_view_arm2_ab_e70abab664b9b19e38f50d9580e851cafa4f60e9a2ff1232bb3c6f3f00ff965c.json"),
    "global_temporal_overlay": Path("reports/v3/global_temporal_overlay_arm3_ab_e859cddac566317686515afc564101fbb946cd6cfe031d18409579ba50d4f774.json"),
    "duplicate_family_overlay": Path("reports/v3/duplicate_family_overlay_arm4_ab_98fcc02eb3aeeed4ce0431512ffed11976920c37f05d32adaf016561943ee66c.json"),
    "policy_clause_children": Path("reports/v3/policy_clause_children_arm5_ab_28e962c3013bdff3f265c9ac99defd334cef3bd2376a87389ac1eb988dc0d494.json"),
    "faq_title_dedup": Path("reports/v3/faq_title_dedup_arm6_ab_e84b9af19ea03f6814aee2756f6b60a7a3627db4e63fccb79726f7bb3b51c8cb.json"),
    "ocr_structure_readiness": Path("reports/v3/ocr_structure_readiness_arm7_2df3e7b95951efc0298bacdd8722c01b3b41dde7c3f909a2f4bfa26d07fc9a64.json"),
    "table_sidecar_depths": Path("reports/v3/table_sidecar_depth_comparison_cc305112c13b2e1f501830afc8457d6dc15af321a1cccbd91495a66e5aaf08fa.json"),
    "gradio_candidate_integration": Path("reports/v3/gradio_v3_2_candidate_integration_ab_f73fe25e9a71eb0f0076d07776b1ba1d00d30d5aa23d50066f080b5b15c73692.json"),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _decision(report: dict[str, Any]) -> str:
    decision = report.get("decision") or report.get("gate", {}).get("decision")
    if not decision:
        raise RuntimeError("Frozen report has no decision")
    return decision


def build_summary(loaded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    table = loaded["table_atomic_facts"]
    clean = loaded["evidence_clean_view"]
    temporal = loaded["global_temporal_overlay"]
    duplicate = loaded["duplicate_family_overlay"]
    policy = loaded["policy_clause_children"]
    faq = loaded["faq_title_dedup"]
    ocr = loaded["ocr_structure_readiness"]["audit"]
    depths = loaded["table_sidecar_depths"]
    integration = loaded["gradio_candidate_integration"]
    return {
        "summary_schema_version": SUMMARY_VERSION,
        "status": "development_demo_candidates_applied_not_promoted",
        "rows": [
            {
                "improvement": "검색·인용용 clean view 통일",
                "implementation_status": "implemented_ab_no_go",
                "decision": _decision(clean),
                "evidence": "73/82 grounded와 9/82 false-full이 동일해 품질 개선 없음",
            },
            {
                "improvement": "표 row-level atomic fact",
                "implementation_status": "implemented_go_candidate",
                "decision": _decision(table),
                "evidence": "초월 비용 값 행과 전체 희귀도 표 복구, exact offset 100%, 회귀 0",
            },
            {
                "improvement": "전 출처 temporal 계약",
                "implementation_status": "implemented_go_metadata_candidate",
                "decision": _decision(temporal),
                "evidence": "980개 문서 계약화, current gold/citation deny 0, 오래된 공지 자동 만료 0",
            },
            {
                "improvement": "duplicate family 관계",
                "implementation_status": "implemented_go_metadata_candidate",
                "decision": _decision(duplicate),
                "evidence": "7 family/14 member 역할 보존, gold 손실 0, 개발 데모에 역할 메타데이터만 표시하고 문서 병합은 미적용",
            },
            {
                "improvement": "긴 운영정책 조항별 재청킹",
                "implementation_status": "implemented_ab_no_go",
                "decision": _decision(policy),
                "evidence": "late-union 후에도 policy top-10 9/16로 기준선과 동일",
            },
            {
                "improvement": "FAQ 제목 중복 제거",
                "implementation_status": "implemented_ab_no_go",
                "decision": _decision(faq),
                "evidence": "279개/9,960자 제거했으나 top-10 11/14로 동일",
            },
            {
                "improvement": "OCR 구조 복구",
                "implementation_status": "skipped_no_go_precondition",
                "decision": ocr["decision"],
                "evidence": "layout 좌표 0, visual gold group 0; 검증 불가능한 구조 추정은 미구현",
            },
            {
                "improvement": "top-5/10/20 비교",
                "implementation_status": "executed_no_additional_recall",
                "decision": _decision(depths),
                "evidence": "모든 depth 96/109·75/82·회귀 0; 깊이 증가 이득 0",
            },
        ],
        "adoptable_development_candidates": [
            "table_atomic_facts_with_complete_table_group_assembler",
            "global_temporal_overlay_metadata",
            "duplicate_family_overlay_metadata",
        ],
        "not_adopted": [
            "global_evidence_clean_view",
            "policy_clause_children",
            "faq_title_dedup_view",
            "ocr_structure_recovery",
            "sidecar_depth_change",
        ],
        "development_demo": {
            "decision": _decision(integration),
            "enabled_candidates": [
                "table_atomic_facts_with_complete_table_group_assembler",
                "global_temporal_overlay_metadata",
                "duplicate_family_overlay_metadata",
            ],
            "off_on_ab_verified": True,
            "canonical_promoted": False,
        },
        "promotion": {
            "canonical_changed": False,
            "runtime_changed": False,
            "development_demo_changed": True,
            "sealed_canary_run": False,
            "promoted": False,
        },
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# v3.2 미구현 개선안 — 기능별 A/B 최종 감사",
        "",
        "모든 항목은 독립 Arm으로 검토했다. 개선이 없거나 검증 불가능한 파생본은 보존하되 채택하지 않았고, runtime/canonical 승격은 0건이다.",
        "",
        "| 첨부 개선안 | 현재 상태 | 판정 근거 |",
        "|---|---|---|",
    ]
    labels = {
        "implemented_go_candidate": "구현 · GO 후보",
        "implemented_go_metadata_candidate": "구현 · GO 메타데이터 후보",
        "implemented_ab_no_go": "구현/A-B · NO-GO",
        "skipped_no_go_precondition": "선행조건 NO-GO · 의도적 미구현",
        "executed_no_additional_recall": "비교 완료 · 추가 이득 없음",
    }
    for row in summary["rows"]:
        lines.append(
            f"| {row['improvement']} | {labels[row['implementation_status']]} | {row['evidence']} |"
        )
    lines.extend(
        [
            "",
            "## 현재 채택 가능한 개발 후보",
            "",
            "- 표 row atomic fact + complete-table 출력 조립: 초월 가격처럼 희귀도별 값 표를 exact 인용으로 노출한다.",
            "- 전 출처 temporal overlay: 오래된 공지를 날짜만으로 만료시키지 않고 `current_unverified`로 구분한다.",
            "- duplicate family overlay: 이벤트 조건과 상점 가격의 출처 역할을 보존한다.",
            "",
            "세 후보는 OFF/ON A/B를 거쳐 개발 데모에만 연결됐다. production runtime/canonical에는 승격하지 않았으며 새 sealed canary가 다음 필수 게이트다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    loaded = {
        name: json.loads((root / path).read_text(encoding="utf-8"))
        for name, path in REPORTS.items()
    }
    summary = build_summary(loaded)
    summary["canonical_inputs"] = {
        "documents": {"path": DEFAULT_DOCUMENTS.as_posix(), "sha256": file_sha256(root / DEFAULT_DOCUMENTS)},
        "chunks": {"path": DEFAULT_CHUNKS.as_posix(), "sha256": file_sha256(root / DEFAULT_CHUNKS)},
    }
    summary["frozen_report_inputs"] = {
        name: {"path": path.as_posix(), "sha256": file_sha256(root / path)}
        for name, path in REPORTS.items()
    }
    report_dir = root / DEFAULT_REPORT_DIR
    json_bytes = _canonical_json_bytes(summary)
    json_sha = _sha256_bytes(json_bytes)
    json_path = report_dir / f"v3_2_feature_implementation_audit_{json_sha}.json"
    write_immutable(json_path, json_bytes)
    markdown_bytes = _markdown(summary).encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = report_dir / f"v3_2_feature_implementation_audit_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    manifest = {
        "manifest_schema_version": "dnf-v3.2-feature-implementation-audit-manifest-v2",
        "status": summary["status"],
        "inputs": summary["frozen_report_inputs"] | summary["canonical_inputs"],
        "artifacts": {
            "json": {"path": json_path.relative_to(root).as_posix(), "sha256": json_sha},
            "markdown": {"path": markdown_path.relative_to(root).as_posix(), "sha256": markdown_sha},
        },
        "promoted": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / DEFAULT_OUTPUT_DIR / f"v3_2_feature_implementation_audit_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    print(json.dumps({"json": json_path.relative_to(root).as_posix(), "markdown": markdown_path.relative_to(root).as_posix(), "manifest": manifest_path.relative_to(root).as_posix(), "summary": summary}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
