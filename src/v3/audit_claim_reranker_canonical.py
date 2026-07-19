from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, write_immutable
from src.v3.evaluate_claim_reranker import freeze_claim_reranker


AUDITOR_VERSION = "claim-reranker-canonical-auditor-v3.1.0"
REPORT_SCHEMA_VERSION = "claim-reranker-canonical-audit-v3.1"

CANONICAL_CASES = Path(
    "data/v3/evidence/claim_reranker_cases_"
    "e1f2cedb533a9af62051dcf60fca1bdf8489c39e28a3b7724459aa97dbf9fe3a.jsonl"
)
CANONICAL_MANIFEST = Path(
    "data/v3/evidence/claim_reranker_manifest_"
    "32d236a75d30ead63c33530e92ea1349bb8000e6f03615e3783c82f76ce6bd6c.json"
)
CANONICAL_REPORT = Path(
    "reports/v3/claim_reranker_runtime_"
    "f37db5f17f3d20553d14922471c5bf7415ff942b12746dfad6d831a6a0ef1df9.json"
)
V3_2_CASES = Path(
    "data/v3/evidence/claim_reranker_cases_"
    "23e7394199e0a3a30bfad2406e90be80d1f88b4b20c9b24d4f908d49065868e4.jsonl"
)
V3_2_MANIFEST = Path(
    "data/v3/evidence/claim_reranker_manifest_"
    "9fcdf24e5d8b062a681641ef8e2207641dffe1659d8d67b68ff496a0fa8bb5fe.json"
)
V3_2_REPORT = Path(
    "reports/v3/claim_reranker_runtime_"
    "2a929ca9649bffe706c5e1037bdec5c2aaa7639918007d435946fe47b33fdbdf.json"
)
V3_2_ADJUDICATION_ARTIFACTS = (
    Path(
        "data/v3/evaluation/evidence_adjudication_packet_"
        "7be5ede8c340c04b77da100b9b9fc7379105b92b4999038d00c85739d83b7a77.jsonl"
    ),
    Path(
        "data/v3/evaluation/evidence_adjudication_manifest_"
        "060b6f039ce6b3c058e1c8cad1cfc7bec0ab5172f5e1d3683ce5911e58c931cb.json"
    ),
    Path(
        "reports/v3/evidence_adjudication_setup_"
        "a161ab5bbba4c4ac8739d95ea1410e652f28cc5be2c81d9da26ab63f5f057a60.json"
    ),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _selection_changes(
    canonical_rows: list[dict[str, Any]], v3_2_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    v3_2_by_id = {row["case_id"]: row for row in v3_2_rows}
    changes = []
    for canonical in canonical_rows:
        candidate = v3_2_by_id[canonical["case_id"]]
        before = canonical["response"]["citation_chunk_ids"]
        after = candidate["response"]["citation_chunk_ids"]
        if before != after:
            changes.append(
                {
                    "case_id": canonical["case_id"],
                    "question": canonical["question"],
                    "canonical_citation_chunk_ids": before,
                    "v3_2_citation_chunk_ids": after,
                }
            )
    return changes


def audit_canonical_state(root: Path) -> dict[str, Any]:
    canonical_manifest_path = root / CANONICAL_MANIFEST
    v3_2_manifest_path = root / V3_2_MANIFEST
    canonical_manifest = json.loads(canonical_manifest_path.read_text(encoding="utf-8"))
    v3_2_manifest = json.loads(v3_2_manifest_path.read_text(encoding="utf-8"))
    canonical_report = json.loads((root / CANONICAL_REPORT).read_text(encoding="utf-8"))
    v3_2_report = json.loads((root / V3_2_REPORT).read_text(encoding="utf-8"))
    canonical_inputs = canonical_manifest["inputs"]
    v3_2_inputs = v3_2_manifest["inputs"]
    shared_input_names = sorted(
        set(canonical_inputs) & set(v3_2_inputs)
        - {"claim_reranker_source", "evaluator_source"}
    )
    shared_input_mismatches = [
        name
        for name in shared_input_names
        if canonical_inputs[name] != v3_2_inputs[name]
    ]
    current_source_hashes = {
        "claim_reranker_source": file_sha256(root / "src/v3/claim_aware_reranker.py"),
        "evaluator_source": file_sha256(root / "src/v3/evaluate_claim_reranker.py"),
    }
    canonical_source_match = all(
        current_source_hashes[name] == canonical_inputs[name]["sha256"]
        for name in current_source_hashes
    )
    replay = freeze_claim_reranker(root=root)
    canonical_replay_exact = (
        replay["cases_sha256"] == canonical_manifest["cases"]["sha256"]
        and replay["manifest_sha256"] == file_sha256(canonical_manifest_path)
    )
    selection_changes = _selection_changes(
        read_jsonl(root / CANONICAL_CASES), read_jsonl(root / V3_2_CASES)
    )
    gates = {
        "canonical_sources_match_manifest": canonical_source_match,
        "canonical_replay_exact": canonical_replay_exact,
        "shared_immutable_input_mismatches_zero": not shared_input_mismatches,
        "canonical_metric_is_56_of_59": canonical_report["metrics"][
            "reranked_cited_group_hits"
        ]
        == 56,
        "canonical_regressions_zero": canonical_report["metrics"][
            "strict_regressions"
        ]
        == 0,
        "v3_2_metric_is_57_of_59": v3_2_report["metrics"][
            "reranked_cited_group_hits"
        ]
        == 57,
        "v3_2_selection_change_count_one": len(selection_changes) == 1,
    }
    if not all(gates.values()):
        raise RuntimeError(f"Canonical claim-reranker audit failed: {gates}")
    return {
        "canonical": {
            "cases_sha256": file_sha256(root / CANONICAL_CASES),
            "manifest_sha256": file_sha256(canonical_manifest_path),
            "report_sha256": file_sha256(root / CANONICAL_REPORT),
            "cited_group_hits": 56,
            "expected_evidence_groups": 59,
            "strict_regressions": 0,
            "current_source_hashes": current_source_hashes,
            "replay_exact": canonical_replay_exact,
        },
        "v3_2_development": {
            "cases_sha256": file_sha256(root / V3_2_CASES),
            "manifest_sha256": file_sha256(v3_2_manifest_path),
            "report_sha256": file_sha256(root / V3_2_REPORT),
            "cited_group_hits": 57,
            "expected_evidence_groups": 59,
            "strict_regressions": 0,
            "artifact_preserved": True,
            "canonical_promotion": False,
            "status": "development_only_superseded_pending_canary",
            "superseded_two_row_adjudication_artifacts": [
                {
                    "path": path.as_posix(),
                    "sha256": file_sha256(root / path),
                    "status": "superseded_development_only",
                }
                for path in V3_2_ADJUDICATION_ARTIFACTS
            ],
        },
        "shared_immutable_input_names": shared_input_names,
        "shared_immutable_input_mismatches": shared_input_mismatches,
        "code_input_differences": {
            name: {
                "canonical_sha256": canonical_inputs[name]["sha256"],
                "v3_2_sha256": v3_2_inputs[name]["sha256"],
            }
            for name in ("claim_reranker_source", "evaluator_source")
        },
        "selection_changes": selection_changes,
        "gates": gates,
        "decisions": {
            "reproducible_canonical": "56_of_59_v3_1",
            "v3_2_57_of_59": "DEVELOPMENT-ONLY",
            "new_reranker_heuristics": "PROHIBITED_THIS_CYCLE",
            "early_generalization_canary": "REQUIRED_BEFORE_PROMOTION",
        },
    }


def freeze_audit(root: Path) -> dict[str, Any]:
    audit = audit_canonical_state(root)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        **audit,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / f"claim_reranker_canonical_audit_{report_sha}.json"
    write_immutable(report_path, report_bytes)
    change = audit["selection_changes"][0]
    markdown = f"""# DNF RAG v3 claim reranker canonical audit

## 판정

- 재현 가능한 canonical: **v3.1 56/59**, strict regression 0
- v3.2 57/59: **development-only**, artifact 보존, 승격 안 함
- shared immutable input mismatch: **0**
- 실제 citation 선택 변경: **1건**

동일한 문서·청크·dev·baseline runtime·BGE·temporal overlay에서 source code와
evaluator code만 달랐다. 선택이 달라진 질문은 `{change['question']}`이다.
canonical source SHA-256은 manifest와 정확히 일치하고 cases/manifest replay도
동일하다. v3.2는 canary 일반화 확인 전까지 canonical로 사용할 수 없다.
"""
    markdown_bytes = markdown.encode("utf-8")
    markdown_sha = _sha256_bytes(markdown_bytes)
    markdown_path = root / "reports/v3" / f"claim_reranker_canonical_audit_{markdown_sha}.md"
    write_immutable(markdown_path, markdown_bytes)
    return {
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "report_markdown_path": str(markdown_path),
        "report_markdown_sha256": markdown_sha,
        "decisions": audit["decisions"],
        "gates": audit["gates"],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = parse_args().root.resolve()
    print(json.dumps(freeze_audit(root), ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit claim-reranker canonical state")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


if __name__ == "__main__":
    main()
