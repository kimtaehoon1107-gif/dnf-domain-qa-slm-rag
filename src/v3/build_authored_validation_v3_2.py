from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable


BUILDER_VERSION = "authored-validation-v3.2-builder-v1.0"
SCHEMA_VERSION = "authored-validation-v3.2"
MANIFEST_SCHEMA_VERSION = "authored-validation-v3.2-manifest-v1"
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_CONTRACT = Path("docs/v3/authored_validation_v3_2.md")


SLOTS: tuple[dict[str, Any], ...] = (
    {
        "source_id": "dnf_notice",
        "title": "신규 결제수단 퀵계좌이체 오픈 안내",
        "question": "퀵계좌이체의 1회·1일·1개월 결제 한도와 하루 횟수 제한을 정리해줘.",
        "spans": [
            "| 1회(만원) | 50 |",
            "| 1일(만원) | 200 |",
            "| 1월(만원) | 500 |",
            "| 1일 횟수 제한 | 없음 |",
        ],
    },
    {
        "source_id": "dnf_notice",
        "title": "7/24(목) 확인된 오류 안내",
        "question": "7월 24일 진 각성의 서 아바타 오류는 어떤 직업에 발생했고 어떻게 수정됐어?",
        "spans": [
            "* 진 각성의 서 아바타를 총검사, 다크나이트, 크리에이터로 선택 시 다른 직업의 아바타가 등장하는 현상",
            "※ 7/24(목) 클라이언트 패치를 통해 오류 수정되었습니다.",
        ],
    },
    {
        "source_id": "dnf_notice",
        "title": "7/24(목) 불량이용자 단속결과 안내",
        "question": "7월 24일 단속 결과에서 비인가 프로그램 사용은 몇 건이었어?",
        "spans": ["▣ 비인가 프로그램 사용 (312건)"],
    },
    {
        "source_id": "dnf_update",
        "title": "5/21(목) 정기점검 업데이트 안내",
        "question": "광휘의 행로 탐사에 필요한 최소 명성과 동시에 진행할 수 있는 탐사 수는 어떻게 돼?",
        "spans": [
            "- 명성 58,950 이상의 캐릭터로 탐사를 진행할 수 있습니다.",
            "- 탐사는 계정 단위로 진행되며, 한 번에 하나의 탐사만 진행할 수 있습니다.",
        ],
    },
    {
        "source_id": "dnf_update",
        "title": "6/18(목) 정기점검 업데이트 안내",
        "question": "브레이커 타이드 바운드의 쿨타임은 6월 18일 업데이트에서 어떻게 바뀌었어?",
        "spans": ["- 쿨타임이 감소합니다. (20초 → 18초)"],
    },
    {
        "source_id": "dnf_update",
        "title": "6/25(목) 정기점검 업데이트 안내",
        "question": "보이드 소울 2개 상품의 초월의 의지 판매 가격은 6월 25일에 어떻게 조정됐어?",
        "spans": ["- 초월의 의지 50개 → 초월의 의지 25개"],
    },
    {
        "source_id": "dnf_event",
        "title": "레바vs낡은창고 드로잉쇼 이모티콘",
        "question": "드로잉쇼 특별 보급품 쿠폰은 계정당 몇 번 입력할 수 있고 우편 보관 기간은 며칠이야?",
        "spans": [
            "- 모든 쿠폰은 계정당 1회 입력 가능합니다.",
            "- 쿠폰 입력 시 아이템은 모험단 우편함으로 지급됩니다. (우편 보관 기간 15일)",
        ],
    },
    {
        "source_id": "dnf_event",
        "title": "인파이터(여)&브레이커의 Special Gift",
        "question": "인파이터(여)·브레이커 스페셜 기프트의 기간과 보상 삭제 시각을 알려줘.",
        "spans": [
            "| 2026년 5월 20일(수) ~ 8월 27일(목) 점검 전",
            "*보상은 별도 표기되지 않은 경우 계정귀속, 2026년 8월 27일 06시 일괄 삭제 상태로 지급됩니다.",
        ],
    },
    {
        "source_id": "dnf_event",
        "title": "아라드 패스 2026 시즌3",
        "question": "아라드 로얄 패스와 캐릭터 추가 지정권은 각각 몇 세라야?",
        "spans": [
            "아라드 로얄 패스\n29,800 세라",
            "로얄 패스\n캐릭터 추가 지정권\n9,800 세라",
        ],
    },
    {
        "source_id": "dnf_game_guide",
        "title": "캐릭터 생성",
        "question": "서버가 달라도 길드와 파티 플레이가 가능한지, 서버 단위로 남는 시스템은 무엇인지 알려줘.",
        "spans": [
            "* 서버는 통합 서버로 적용되어 길드 가입 및 파티 플레이에 영향을 받지 않습니다.",
            "* 단, 계정금고 등 일부 시스템의 경우에는 서버 단위로 적용되므로 여러 캐릭터를 키울 때는 하나의 서버에서 육성을 하는 것이 좋습니다.",
        ],
    },
    {
        "source_id": "dnf_game_guide",
        "title": "융합무기",
        "question": "바칼 융합 무기 제작에서 타입이 달라도 되는지와 강화된 장비를 재료로 쓸 수 있는지 알려줘.",
        "spans": [
            "- 바칼 무기는 재료로 사용되는 무기의 타입이 동일하지 않아도 제작이 가능 합니다.",
            "- 강화/증폭/재련/마법부여된 장비는 재료로 사용 할 수 없습니다.",
        ],
    },
    {
        "source_id": "dnf_game_guide",
        "title": "모험 도감",
        "question": "캐릭터 컬렉션 등록에 필요한 레벨과 각성 조건은 무엇이야?",
        "spans": ["90레벨 이상이며, 2차각성 또는 자각을 완료하면 캐릭터 컬렉션에 해당 전직이 등록됩니다."],
    },
    {
        "source_id": "dnf_faq",
        "title": "[마이핀] 마이핀(My-PIN)이란 무엇인가요?",
        "question": "마이핀은 몇 자리 번호이고 유효기간과 연간 재발급 한도는 어떻게 돼?",
        "spans": [
            "마이핀은 인터넷이 아닌 일상생활에서 사용할 수 있는 본인 확인 수단으로\n개인정보를 포함하고 있지 않은 13자리 무작위 번호입니다. (유효기간 3년)",
            "- 마이핀은 당해 연도 기준으로 연 5회까지 재 발급이 가능합니다.",
        ],
    },
    {
        "source_id": "dnf_faq",
        "title": "[이용 문의] 캐릭터 검색이 되지 않아요.",
        "question": "던파ON 캐릭터 검색에 나타나려면 최근 접속 기간과 최소 레벨이 어떻게 돼?",
        "spans": ["[캐릭터 검색] 기능은 최근 90일 이내 게임에 접속한\n11레벨 이상의 캐릭터 만 조회되고 있습니다."],
    },
    {
        "source_id": "dnf_faq",
        "title": "[간편잠금] 간편잠금이 무엇인가요?",
        "question": "던파ON 간편잠금은 몇 자리 비밀번호를 쓰고 홈페이지에서는 무엇으로 해지할 수 있어?",
        "spans": ["잠금/해지는 연동을 할 때 설정한 비밀번호(숫자 6자리)를 이용하여 할 수 있으며\n홈페이지 휴대폰 인증을 통해서도 해지할 수 있습니다."],
    },
    {
        "source_id": "dnf_account_policy",
        "title": "던전앤파이터 운영정책 (2024-10-10 시행)",
        "question": "2024년 10월 10일 운영정책에서 이용제한 이의신청 데이터는 얼마나 보유했어?",
        "spans": ["단, 이용제한 근거에 대한 데이터는 관계 법령에 근거하여 90일간 보유하고 있으며, 데이터 보유 기간 경과 시 이의 신청이 불가합니다."],
        "time_scope": "historical",
    },
    {
        "source_id": "dnf_account_policy",
        "title": "던전앤파이터 운영정책 (2024-11-16 시행)",
        "question": "2024년 11월 16일 운영정책에서는 길드 마스터가 몇 일 이상 접속하지 않으면 권한 위임이 가능했어?",
        "spans": ["길드 마스터가 장기 미접속, 이용제한 등의 사유로 30일 이상 접속하지 않은 경우 길드 마스터 권한이 다른 길드원에게 위임될 수 있습니다."],
        "time_scope": "historical",
    },
    {
        "source_id": "dnf_account_policy",
        "title": "던전앤파이터 운영정책 (2024-05-18 시행)",
        "question": "2024년 5월 18일 정책에서 일반 채팅정책 위반의 1차와 2차 제한 기간은 각각 얼마였어?",
        "spans": ["| 채팅정책 위반(일반) | 3일 채팅 이용제한 | 7일 채팅 이용제한 | 10일 채팅 이용제한 | 30일 채팅 이용제한 * 4차 이후 동일 적용 |"],
        "time_scope": "historical",
    },
    {
        "source_id": "dnf_seria_shop",
        "title": "해방의 계약",
        "question": "해방의 계약 30일 상품의 가격과 거래 타입은 무엇이야?",
        "spans": [
            "| 거래타입 | 교환불가 |",
            "| 판매가격 | 9,800 세라 |",
        ],
    },
    {
        "source_id": "dnf_seria_shop",
        "title": "내금고 Ⅰ & 내금고 Ⅱ & 계정금고 상세 안내",
        "question": "은 금고와 세련된 은 금고는 각각 몇 칸이고 가격은 몇 세라야?",
        "spans": [
            "| 은 금고 | 40 칸 | 400 세라 |",
            "| 세련된 은 금고 | 56 칸 | 800 세라 |",
        ],
    },
    {
        "source_id": "dnf_seria_shop",
        "title": "세리아의 성장지원/정착지원 패키지",
        "question": "세리아 성장지원 패키지의 가격, 계정당 구매 한도, 청약철회 가능 여부를 알려줘.",
        "spans": [
            "- 계정귀속 패키지 : 4,900 세라",
            "- 계정당 5회 구매 가능",
            "- 세리아의 성장지원 패키지는 청약 철회 가능 상품입니다.",
        ],
    },
    {
        "source_id": "dnf_monthly_item",
        "title": "7월 이달 의 아이템",
        "question": "2025년 7월 이달의 아이템은 상점판매가격과 거래타입, 삭제일이 어떻게 됐어?",
        "spans": [
            "| 상점판매가격 | 4,000만 골드 |",
            "| 거래타입 | 교환가능 |",
            "| 삭제일자 | 2025년 08월 14일 06시 일괄삭제 |",
        ],
        "time_scope": "historical",
    },
    {
        "source_id": "dnf_monthly_item",
        "title": "9월 이달 의 아이템",
        "question": "2025년 9월 시브의 보조장비 보주는 가격, 거래타입, 사용기간이 어떻게 안내됐어?",
        "spans": [
            "| 상점판매가격 | 4,000만 골드 |",
            "| 거래타입 | 1회 교환가능(거래 후 계정귀속) |",
            "* 시브의 보조장비 보주는 기간 무제한 아이템입니다.",
        ],
        "time_scope": "historical",
    },
    {
        "source_id": "dnf_monthly_item",
        "title": "새해맞이 이달 의 아이템 이벤트",
        "question": "2026년 새해맞이 해방의 부스터 던전 버프는 언제 적용됐고 어떤 효과였어?",
        "spans": [
            "#적용 기간 : 2026년 1월 1일 00시 ~ 2026년 1월 15일 점검 전",
            "- 최종 데미지 5% 증가",
            "- 공격/캐스트/이동 속도 10% 증가",
        ],
        "time_scope": "historical",
    },
)


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _case_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return f"authored_validation_v3_2_sha256_{digest}"


def build_rows(
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    prior_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(SLOTS) != 24:
        raise RuntimeError("Authored validation must contain 24 slots")
    counts = Counter(slot["source_id"] for slot in SLOTS)
    if set(counts.values()) != {3} or len(counts) != 8:
        raise RuntimeError("Authored validation must contain three slots per source")
    documents_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for document in documents:
        documents_by_key.setdefault((document["source_id"], document["title"]), []).append(document)
    chunks_by_parent: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        chunks_by_parent.setdefault(chunk["parent_document_id"], []).append(chunk)
    prior_parents = {
        document_id for row in prior_rows for document_id in row.get("gold_document_ids", [])
    }
    output = []
    for ordinal, slot in enumerate(SLOTS, 1):
        matches = documents_by_key.get((slot["source_id"], slot["title"]), [])
        if len(matches) != 1:
            raise RuntimeError(f"Expected one source document for slot {ordinal}: {len(matches)}")
        document = matches[0]
        parent_chunks = chunks_by_parent.get(document["document_id"], [])
        evidence_groups = []
        gold_chunk_ids: set[str] = set()
        for group_index, span in enumerate(slot["spans"], 1):
            acceptable = sorted(
                chunk["chunk_id"] for chunk in parent_chunks if span in chunk["display_text"]
            )
            if not acceptable:
                raise RuntimeError(f"Evidence span missing for slot {ordinal}: {span}")
            gold_chunk_ids.update(acceptable)
            evidence_groups.append(
                {
                    "group_id": f"evidence_{group_index}",
                    "evidence_span": span,
                    "acceptable_chunk_ids": acceptable,
                    "document_ids": [document["document_id"]],
                }
            )
        payload = {
            "source_id": slot["source_id"],
            "document_id": document["document_id"],
            "question": slot["question"],
            "evidence_groups": evidence_groups,
        }
        output.append(
            {
                "retrieval_dev_schema_version": SCHEMA_VERSION,
                "dev_id": _case_id(payload),
                "query_ordinal": ordinal,
                "question": slot["question"],
                "answerability": "true",
                "source_ids": [slot["source_id"]],
                "time_scope": slot.get("time_scope", "current"),
                "as_of": "2026-07-22",
                "target_statuses": [document["status"]],
                "gold_document_ids": [document["document_id"]],
                "gold_chunk_ids": sorted(gold_chunk_ids),
                "evidence_groups": evidence_groups,
                "required_evidence_group_count": len(evidence_groups),
                "parent_overlap_with_prior_95": document["document_id"] in prior_parents,
                "difficulty": "authored_validation_v3_2",
                "review_status": "agent_authored_unreviewed",
                "training_allowed": False,
                "final_benchmark_eligible": False,
                "provenance": {
                    "author_id": "codex_same_agent_author",
                    "independent_holdout_claim_allowed": False,
                    "human_reviewed": False,
                },
            }
        )
    return output


def build_and_freeze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "chunks": root / DEFAULT_CHUNKS,
        "documents": root / DEFAULT_DOCUMENTS,
        "adaptive_dev": root / DEFAULT_DEV,
        "downgraded_canary": root / DEFAULT_CANARY,
        "contract": root / DEFAULT_CONTRACT,
        "builder_source": Path(__file__).resolve(),
    }
    before = {name: file_sha256(path) for name, path in inputs.items()}
    rows = build_rows(
        read_jsonl(inputs["documents"]),
        read_jsonl(inputs["chunks"]),
        read_jsonl(inputs["adaptive_dev"]) + read_jsonl(inputs["downgraded_canary"]),
    )
    data = _serialize_jsonl(rows, lambda row: row["query_ordinal"])
    digest = hashlib.sha256(data).hexdigest()
    path = root / "data/v3/evaluation" / f"authored_validation_v3_2_{digest}.jsonl"
    write_immutable(path, data)
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "evaluation_role": "authored_validation_not_independent_not_sealed",
        "frozen_before_first_run": True,
        "inputs": {
            name: {"path": _relative(root, input_path), "sha256": before[name]}
            for name, input_path in inputs.items()
        },
        "artifact": {
            "path": _relative(root, path),
            "sha256": digest,
            "row_count": len(rows),
            "source_counts": dict(sorted(Counter(row["source_ids"][0] for row in rows).items())),
            "prior_parent_overlap_count": sum(row["parent_overlap_with_prior_95"] for row in rows),
        },
        "source_commit": _git_head(root),
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = root / "data/v3/evaluation" / f"authored_validation_v3_2_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    after = {name: file_sha256(path) for name, path in inputs.items()}
    if [name for name in before if before[name] != after[name]]:
        raise RuntimeError("Authored validation inputs changed while freezing")
    return {
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "row_count": len(rows),
        "source_counts": manifest["artifact"]["source_counts"],
        "prior_parent_overlap_count": manifest["artifact"]["prior_parent_overlap_count"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze the v3.2 authored validation set")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build_and_freeze(parse_args().root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
