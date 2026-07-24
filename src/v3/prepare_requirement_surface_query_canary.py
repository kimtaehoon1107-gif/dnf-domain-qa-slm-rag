from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.answer_target_router import _kiwi
from src.v3.build_corpus import file_sha256
from src.v3.collect_details import _canonical_json_bytes, _serialize_jsonl, write_immutable
from src.v3.korean_particles import attach_object, validate_particle_tokens
from src.v3.requirement_surface_query import extract_entity_coordinated_surfaces


BUILDER_VERSION = "requirement-surface-query-authored-canary-v1.2.0"
CANDIDATE_SCHEMA_VERSION = "requirement-surface-query-authored-candidate-v1.2"
DEFAULT_SOURCE = Path("src/v3/prepare_requirement_surface_query_canary.py")
DEFAULT_PARTICLE_SOURCE = Path("src/v3/korean_particles.py")
DEFAULT_PLAN = Path(
    "data/v3/evaluation/requirement_surface_query_canary_plan_"
    "951ebe37183f778a5da3e694af4d90897da059ce6c6955f198b8058f75d159bc.jsonl"
)
DEFAULT_CONTRACT_MANIFEST = Path(
    "data/v3/evaluation/requirement_surface_query_canary_manifest_"
    "20c10e485c67ea1933968e53fd25b2fc9060d360626487a85ef2ab3cc2d602b2.json"
)
DEFAULT_DOCUMENTS = Path(
    "data/v3/normalized/documents_dnf_official_detail_v3.1_"
    "d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d.jsonl"
)
DEFAULT_CHUNKS = Path(
    "data/v3/chunks/chunks_dnf_official_v3.1_"
    "bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl"
)
DEFAULT_DEV = Path(
    "data/v3/evaluation/retrieval_dev_v3.1_"
    "b98d62e1e3920f9e4a58bd602aa6cda1036827d1122f51d3478a95aa8d1a2978.jsonl"
)
DEFAULT_DOWNGRADED_CANARY = Path(
    "data/v3/evaluation/early_generalization_authored_canary_"
    "28b0aa6c06add6ae0b81a7888d0f0c71bc46450058f6cedcb1588a5cdd83b85d.jsonl"
)
DEFAULT_AUTHORED_VALIDATION = Path(
    "data/v3/evaluation/authored_validation_v3_2_"
    "52c1b84ef7ab0f9bee29931c46f9febf0970492216b6742e8f5337282af4181e.jsonl"
)
DEFAULT_TABLE_FACTS = Path(
    "data/v3/structured/table_atomic_facts_v3.2_"
    "1f29fca9252c6a23f049fe6663aac1856357d3d7341470f70cad9fdc38034f3a.jsonl"
)
DEFAULT_PREVIOUS_PACKET = Path(
    "data/v3/evaluation/requirement_surface_query_canary_candidate_"
    "7a1408a2fcabc9c113906e4d8330d5478ab523916ed634307d325c41fc44aba1.jsonl"
)
DEFAULT_AMENDMENT = Path(
    "docs/v3/requirement_surface_query_canary_ord12_refreeze_amendment.md"
)

REVIEW_REJECTED_SLOT_ORDINALS = frozenset({12})
PROTECTED_APPROVED_FIELDS = (
    "question_text",
    "requirements",
    "evidence_groups",
    "gold_answer",
    "gold_chunk_ids",
    "gold_document_ids",
)
REVIEWED_CURRENT_UNVERIFIED = {
    "validity_state": "current_unverified",
    "retrieval_action_current": "allow_with_warning",
    "superseded_by": None,
}


def _fact(
    surface: str,
    relation: str,
    value_type: str,
    evidence_span: str,
    *,
    subject: str | None = None,
    table_atomic_attribute: str | None = None,
    table_row_text: str | None = None,
    exact_chunk_id: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "surface": surface,
        "relation": relation,
        "value_type": value_type,
        "evidence_span": evidence_span,
        "subject": subject or "",
    }
    if table_atomic_attribute is not None:
        row["table_atomic_attribute"] = table_atomic_attribute
        row["table_row_text"] = table_row_text
    if exact_chunk_id is not None:
        if start_offset is None or end_offset is None:
            raise ValueError("Exact chunk evidence requires both start and end offsets")
        row["exact_chunk_id"] = exact_chunk_id
        row["start_offset"] = start_offset
        row["end_offset"] = end_offset
    return row


BASES: dict[str, dict[str, dict[str, Any]]] = {
    "dnf_notice": {
        "a": {
            "entity": "최후의 조율자",
            "document_prefix": "document_sha256_cc9ba273",
            "control_question_prefix": "3/26 패치에서 ",
            "positive_question": "3/26 패치에서 최후의 조율자의 천칭 파괴 오류 처리와 Y축 피격 판정 조정은 어떻게 됐어?",
            "facts": [
                _fact(
                    "천칭 파괴 오류 처리",
                    "조율의 천칭 파괴 오류 처리",
                    "status_change",
                    "최후의 조율자 - 간헐적으로 조율의 천칭이 파괴되지 않는 현상이 수정됩니다.",
                ),
                _fact(
                    "Y축 피격 판정 조정",
                    "Y축 피격 판정 조정",
                    "status_change",
                    "최후의 조율자 - 조율의 천칭과 일반 몬스터의 Y축 피격 판정이 조정됩니다.",
                ),
            ],
        },
        "b": {
            "entity": "네이버 로그인 계정",
            "document_prefix": "document_sha256_0d1b0328",
            "positive_question": "네이버 로그인 계정의 접속 주소와 계정 종류는 어떻게 유지돼?",
            "facts": [
                _fact(
                    "접속 주소",
                    "로그인 페이지 접속 주소",
                    "url_behavior",
                    "로그인 페이지 접속 주소(URL)는 동일합니다. : 기존과 똑같이 넥슨 로그인 페이지로 접속해 주세요.",
                ),
                _fact(
                    "계정 종류",
                    "계정 종류 유지 여부",
                    "status",
                    "계정 종류는 유지됩니다. : 넥슨 ID가 네이버 채널링 계정으로 바뀌지 않습니다.",
                ),
                _fact(
                    "로그인 방법",
                    "로그인 방법 변경",
                    "procedure",
                    "로그인 방법만 바뀝니다. : 넥슨 로그인 화면에서 아이디/비밀번호를 입력하는 대신, [네이버 아이콘] 을 클릭해서 로그인 하는 형태로 변경됩니다.",
                ),
            ],
        },
    },
    "dnf_update": {
        "a": {
            "entity": "던파ON",
            "document_prefix": "document_sha256_5a6c85fe",
            "reviewed_temporal_metadata": REVIEWED_CURRENT_UNVERIFIED,
            "positive_question": "던파ON의 2.0.19 적용 시점과 다운로드 시작 시각은 어떻게 돼?",
            "facts": [
                _fact(
                    "2.0.19 적용 시점",
                    "2.0.19 버전 적용일",
                    "date",
                    "6/25(목) 적용되는 던파ON 2.0.19 버전 업데이트 안내 드립니다.",
                ),
                _fact(
                    "다운로드 시작 시각",
                    "2.0.19 다운로드 시작 시각",
                    "datetime",
                    "2.0.19 버전은 6/25(목) 오전 9시부터 구글 플레이 스토어 및 앱스토어에서 다운로드 가능합니다.",
                ),
            ],
        },
        "b": {
            "entity": "해방된 흉몽(챌린지)",
            "document_prefix": "document_sha256_f45dc64d",
            "reviewed_temporal_metadata": REVIEWED_CURRENT_UNVERIFIED,
            "positive_question": "해방된 흉몽(챌린지) 버프의 공격속도 증가치와 캐스트속도 증가치는 얼마야?",
            "facts": [
                _fact("공격속도 증가치", "공격속도 증가", "percentage", "- 공격속도 20% 증가"),
                _fact("캐스트속도 증가치", "캐스트속도 증가", "percentage", "- 캐스트속도 20% 증가"),
                _fact("이동속도 증가치", "이동속도 증가", "percentage", "- 이동속도 20% 증가"),
            ],
        },
    },
    "dnf_event": {
        "a": {
            "entity": "트리니티",
            "document_prefix": "document_sha256_d1016968",
            "positive_question": "트리니티 랭킹의 노출 순위 범위와 갱신 주기는 어떻게 돼?",
            "facts": [
                _fact("노출 순위 범위", "전체 랭킹 노출 범위", "rank_range", "- 전체 랭킹은 1~100위까지 노출됩니다."),
                _fact("갱신 주기", "랭킹 갱신 주기", "duration", "- 랭킹은 1분 단위로 갱신됩니다."),
            ],
        },
        "b": {
            "entity": "트로피컬 바캉스 패키지",
            "document_prefix": "document_sha256_bcdc92cb",
            "positive_question": "트로피컬 바캉스 패키지의 판매 기간과 첫 구매 혜택은 어떻게 돼?",
            "facts": [
                _fact(
                    "판매 기간",
                    "판매 기간",
                    "date_range",
                    "판매 기간: 2026년 6월 4일(목) 점검 후 ~ 8월 27일(목) 점검 전",
                ),
                _fact(
                    "첫 구매 혜택",
                    "첫 구매 혜택",
                    "item",
                    "EVENT 첫 구매 혜택! 열대야의 추억 오라 확정 변경권 지급!",
                ),
                _fact(
                    "혜택 삭제 시각",
                    "열대야의 추억 오라 확정 변경권 삭제 시각",
                    "datetime",
                    "열대야의 추억 오라 확정 변경권\n교환불가 트로피컬 바캉스 오라 아바타에 사용 시\n확정적으로 열대야의 추억 오라 아바타(교환불가)를 얻을 수 있습니다.\n[사용 가능 오라]\n- 청량한 바다의 기억\n- 따스한 노을의 기억\n[획득 가능 오라]\n- 열대야의 추억\n계정귀속, 2026년 8월 27일 06시 일괄 삭제",
                    exact_chunk_id="chunk_sha256_8bacceaaf7f9215dd9837f65d63dc4491d3b53429fe963e5c66c1bc1322473c2",
                    start_offset=65,
                    end_offset=235,
                ),
            ],
        },
    },
    "dnf_game_guide": {
        "a": {
            "entity": "장비 계승",
            "document_prefix": "document_sha256_5348",
            "positive_question": "장비 계승의 사용 가능 장비 등급과 동일 부위 조건은 어떻게 돼?",
            "facts": [
                _fact(
                    "사용 가능 장비 등급",
                    "사용 가능한 장비 등급과 거래 상태",
                    "eligibility",
                    "계승은 레어 등급 이상 레어리티의 교환불가 장비 아이템에만 사용 가능합니다.(115레벨 기준)",
                ),
                _fact(
                    "동일 부위 조건",
                    "동일 부위 요구",
                    "condition",
                    "4. 계승은 부위가 동일한 장비만 진행할 수 있습니다.",
                ),
            ],
        },
        "b": {
            "entity": "장비 점수",
            "document_prefix": "document_sha256_b1f9429b",
            "positive_question": "장비 점수의 캐릭터 스킬 반영 여부와 유틸 전용 장비 계산 여부는 어떻게 돼?",
            "facts": [
                _fact(
                    "캐릭터 스킬 반영 여부",
                    "캐릭터별 스킬 정보 반영",
                    "boolean",
                    "캐릭터 별 스킬 정보는 적용되지 않으며, 캐릭터별로 효율이 다른 장비 및 옵션들은 통일된 규칙으로 계산됩니다.",
                ),
                _fact(
                    "유틸 전용 장비 계산 여부",
                    "유틸 옵션 전용 장비 점수 계산",
                    "boolean",
                    "데미지 옵션 없이 유틸 옵션으로만 구성된 장비의 경우 장비 점수가 계산되지 않습니다.",
                ),
                _fact(
                    "데미지·유틸 선택 장비 처리",
                    "데미지와 유틸 선택형 장비 점수 처리",
                    "rule",
                    "단, 하나의 장비에서 데미지 옵션과 유틸 옵션을 선택하여 적용하는 경우, 일괄적으로 데미지 옵션의 점수가 부여됩니다.",
                ),
            ],
        },
    },
    "dnf_faq": {
        "a": {
            "entity": "보안카드",
            "document_prefix": "document_sha256_d735",
            "positive_question": "보안카드의 폐기 인증 방법과 재발급 위치는 어디야?",
            "facts": [
                _fact(
                    "폐기 인증 방법",
                    "폐기 본인인증 방법",
                    "procedure",
                    "홈페이지에서 휴대폰 혹은 신용/체크카드 인증을 통해 폐기할 수 있습니다.",
                ),
                _fact(
                    "재발급 위치",
                    "재발급 위치",
                    "location",
                    "보안카드 재발급은 게임 내에서 직접 하실 수 있습니다.",
                ),
            ],
        },
        "b": {
            "entity": "세라 환불",
            "document_prefix": "document_sha256_e080",
            "positive_question": "세라 환불 안내의 결제취소 의미와 환불 대상은 어떻게 달라?",
            "facts": [
                _fact(
                    "결제취소 의미",
                    "결제취소 정의",
                    "definition",
                    "충전 후 사용하지 않는 금액에 대해 결제 전 상태로 되돌리는 것을 뜻하며",
                ),
                _fact(
                    "환불 대상",
                    "환불 대상 금액",
                    "eligibility",
                    "결제취소 기간이 지난, 충전 후 미사용 금액에 대해서는 환불을 진행할 수 있습니다.",
                ),
                _fact(
                    "환불 입금 계좌",
                    "환불금 입금 대상",
                    "destination",
                    "환불되는 금액은 서류 검토 후 결제 명의자의 통장으로 입금됩니다.",
                ),
            ],
        },
    },
    "dnf_account_policy": {
        "a": {
            "entity": "길드",
            "document_prefix": "document_sha256_c7b4",
            "positive_question": "길드의 탈퇴 후 재가입 시점과 장기 미접속 마스터 권한 위임 조건은 어떻게 돼?",
            "facts": [
                _fact(
                    "탈퇴 후 재가입 시점",
                    "길드 탈퇴 후 재가입 가능 시점",
                    "datetime_rule",
                    "길드 탈퇴 시 오전 06시 피로도 초기화 이후부터 재가입이 가능합니다.",
                ),
                _fact(
                    "장기 미접속 마스터 권한 위임 조건",
                    "길드 마스터 권한 위임 조건",
                    "condition",
                    "길드 마스터가 장기 미접속, 이용제한 등의 사유로 30일 이상 접속하지 않은 경우 길드 마스터 권한이 다른 길드원에게 위임될 수 있습니다.",
                ),
            ],
        },
        "b": {
            "entity": "길드",
            "document_prefix": "document_sha256_c7b4",
            "positive_question": "길드 해제의 명예훼손 사유와 사칭·사기 사유는 어떻게 규정돼?",
            "facts": [
                _fact("명예훼손 사유", "길드 해제 명예훼손 사유", "violation", "① 특정 개인이나 단체에 대한 비난이나 명예 훼손을 하는 경우"),
                _fact("사칭·사기 사유", "길드 해제 사칭 또는 사기 사유", "violation", "② 타인 또는 업체를 사칭하거나 사기 목적의 행위를 하는 경우"),
                _fact("영리 홍보 사유", "길드 해제 영리 홍보 사유", "violation", "③ 영리를 목적으로 홍보 활동 또는 영업 행위를 하는 경우"),
            ],
        },
    },
    "dnf_seria_shop": {
        "a": {
            "entity": "염색약",
            "document_prefix": "document_sha256_69dba48b",
            "positive_question": "염색약의 염색제거약 가격과 거래 타입은 어떻게 돼?",
            "single_control_evidence_spans": [
                "| 염색제거약 | 100,000 골드 | 계정귀속 | 우클릭한 뒤, 게임 화면에 나타나는 염색창에 염색한 아바타를 넣으면 세라샵에서 구매할 당시의 색상으로 되돌릴 수 있습니다. 피부 아바타, 클론 아바타, 오라 아바타, 기자단 아바타, 무기 아바타, 단진의 망토류, 항아리 모자류, 착용중인 아바타는 사용할 수 없습니다. 사용시 염색제거약이 소멸됩니다. 마을에서만 사용 가능합니다. | 무제한 | |"
            ],
            "facts": [
                _fact(
                    "염색제거약 가격",
                    "염색제거약 가격",
                    "price",
                    "100,000 골드",
                    subject="염색제거약",
                    table_atomic_attribute="아이템 가격",
                    table_row_text="| 염색제거약 | 100,000 골드 | 계정귀속 | 우클릭한 뒤, 게임 화면에 나타나는 염색창에 염색한 아바타를 넣으면 세라샵에서 구매할 당시의 색상으로 되돌릴 수 있습니다. 피부 아바타, 클론 아바타, 오라 아바타, 기자단 아바타, 무기 아바타, 단진의 망토류, 항아리 모자류, 착용중인 아바타는 사용할 수 없습니다. 사용시 염색제거약이 소멸됩니다. 마을에서만 사용 가능합니다. | 무제한 | |",
                ),
                _fact(
                    "염색제거약 거래 타입",
                    "염색제거약 거래 타입",
                    "trade_type",
                    "계정귀속",
                    subject="염색제거약",
                    table_atomic_attribute="거래타입",
                    table_row_text="| 염색제거약 | 100,000 골드 | 계정귀속 | 우클릭한 뒤, 게임 화면에 나타나는 염색창에 염색한 아바타를 넣으면 세라샵에서 구매할 당시의 색상으로 되돌릴 수 있습니다. 피부 아바타, 클론 아바타, 오라 아바타, 기자단 아바타, 무기 아바타, 단진의 망토류, 항아리 모자류, 착용중인 아바타는 사용할 수 없습니다. 사용시 염색제거약이 소멸됩니다. 마을에서만 사용 가능합니다. | 무제한 | |",
                ),
            ],
        },
        "b": {
            "entity": "계약&기간제",
            "document_prefix": "document_sha256_c5361c7c",
            "positive_question": "계약&기간제의 가브리엘/배니부 3일 가격과 거래 타입은 어떻게 돼?",
            "facts": [
                _fact(
                    "가브리엘/배니부 3일 가격",
                    "가브리엘/배니부의 계약 3일 가격",
                    "price",
                    "3,100 세라 3,100,000 골드",
                    subject="가브리엘/배니부의 계약 3일",
                    table_atomic_attribute="아이템 가격",
                    table_row_text="| 가브리엘/배니부의 계약 3일 | 3,100 세라 3,100,000 골드 | 계정귀속 | 3일간 가브리엘/배니부의 계약을 맺습니다. 가브리엘/배니부의 등장 확률과 판매 종류 및 개수가 증가합니다.(단, 에픽조각교환 가브리엘은 제외) | 수령 시 즉시 적용 |",
                ),
                _fact(
                    "거래 타입",
                    "가브리엘/배니부의 계약 3일 거래 타입",
                    "trade_type",
                    "계정귀속",
                    subject="가브리엘/배니부의 계약 3일",
                    table_atomic_attribute="거래타입",
                    table_row_text="| 가브리엘/배니부의 계약 3일 | 3,100 세라 3,100,000 골드 | 계정귀속 | 3일간 가브리엘/배니부의 계약을 맺습니다. 가브리엘/배니부의 등장 확률과 판매 종류 및 개수가 증가합니다.(단, 에픽조각교환 가브리엘은 제외) | 수령 시 즉시 적용 |",
                ),
                _fact(
                    "적용 시점",
                    "가브리엘/배니부의 계약 3일 적용 시점",
                    "activation",
                    "수령 시 즉시 적용",
                    subject="가브리엘/배니부의 계약 3일",
                    table_atomic_attribute="기간제한",
                    table_row_text="| 가브리엘/배니부의 계약 3일 | 3,100 세라 3,100,000 골드 | 계정귀속 | 3일간 가브리엘/배니부의 계약을 맺습니다. 가브리엘/배니부의 등장 확률과 판매 종류 및 개수가 증가합니다.(단, 에픽조각교환 가브리엘은 제외) | 수령 시 즉시 적용 |",
                ),
            ],
        },
    },
    "dnf_monthly_item": {
        "a": {
            "entity": "이달의 아이템",
            "document_prefix": "document_sha256_e1b41518",
            "reviewed_temporal_metadata": REVIEWED_CURRENT_UNVERIFIED,
            "positive_question": "이달의 아이템의 판매 기간과 상점 판매가는 어떻게 돼?",
            "facts": [
                _fact("판매 기간", "판매 기간", "date_range", "판매기간: 06.25 ~ 07.30"),
                _fact("상점 판매가", "상점 판매가", "price", "4,000만 골드"),
            ],
        },
        "b": {
            "entity": "이달의 아이템",
            "document_prefix": "document_sha256_e1b41518",
            "reviewed_temporal_metadata": REVIEWED_CURRENT_UNVERIFIED,
            "positive_question": "이달의 아이템의 거래 타입과 삭제 시각은 어떻게 돼?",
            "facts": [
                _fact("거래 타입", "거래 타입", "trade_type", "교환가능"),
                _fact("삭제 시각", "삭제 시각", "datetime", "2026년 08월 13일 06시 일괄삭제"),
                _fact(
                    "사용 시 획득 구성",
                    "사용 시 획득 아이템 구성",
                    "item_list",
                    "사용 시 [7월]클론 레어 아바타(교환불가) 풀세트 상자, [7월]찬란한 엠블렘(계정귀속) 풀세트 선택상자를 획득할 수 있습니다.",
                ),
            ],
        },
    },
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _resolve_prefix(rows: list[dict[str, Any]], key: str, prefix: str) -> dict[str, Any]:
    matches = [row for row in rows if str(row[key]).startswith(prefix)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {key} for {prefix}, found {len(matches)}")
    return matches[0]


def _build_requirement(
    fact: dict[str, str], entity: str, ordinal: int
) -> dict[str, Any]:
    subject = fact["subject"] or entity
    return {
        "requirement_id": f"requirement_{ordinal}",
        "subject": subject,
        "relation": fact["relation"],
        "value_type": fact["value_type"],
        "subject_group": entity,
        "surface": fact["surface"],
        "entity_anchor": {
            "phrase": entity,
            "status": "author_expected_requires_human_review",
        },
    }


def _question_for(base: dict[str, Any], stratum: str) -> str:
    if stratum.startswith("positive"):
        return base["positive_question"]
    if stratum == "single_requirement_control":
        prefix = base.get("control_question_prefix", "")
        return f"{prefix}{base['entity']}의 {base['facts'][0]['surface']}만 알려줘."
    surfaces = [fact["surface"] for fact in base["facts"][:3]]
    return (
        f"{base['entity']}의 {surfaces[0]}, {surfaces[1]}, "
        f"{attach_object(surfaces[2])} 모두 알려줘."
    )


def _resolve_table_atomic_fact(
    fact: dict[str, Any],
    document_id: str,
    table_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    matches = [
        row
        for row in table_facts
        if row["parent_document_id"] == document_id
        and row["row_text"] == fact["table_row_text"]
        and row["attribute"] == fact["table_atomic_attribute"]
        and row["value"] == fact["evidence_span"]
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected one table atomic value cell: "
            f"document={document_id} attribute={fact['table_atomic_attribute']} "
            f"value={fact['evidence_span']!r}, found={len(matches)}"
        )
    return matches[0]


def _table_subject_cell(row_text: str) -> str:
    cells = [cell.strip() for cell in row_text.strip().strip("|").split("|")]
    if not cells or not cells[0]:
        raise RuntimeError(f"Table row has no subject cell: {row_text!r}")
    return cells[0]


def _duplicate_scan_unit(evidence_span: str, source_display_text: str) -> str:
    if "\n" in evidence_span or len(evidence_span.strip()) >= 20:
        return evidence_span
    lines = source_display_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != evidence_span.strip():
            continue
        previous = index - 1
        while previous >= 0 and not lines[previous].strip():
            previous -= 1
        if previous >= 0:
            return f"{lines[previous].strip()}\n{line.strip()}"
    return evidence_span


def _duplicate_current_matches(
    *,
    evidence_span: str,
    source_display_text: str,
    document_id: str,
    current_document_ids: set[str],
    documents_by_id: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    table_fact: dict[str, Any] | None,
    table_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: dict[tuple[str, str], dict[str, Any]] = {}
    if table_fact is None:
        scan_unit = _duplicate_scan_unit(evidence_span, source_display_text)
        for chunk in chunks:
            parent_id = chunk["parent_document_id"]
            if (
                parent_id == document_id
                or parent_id not in current_document_ids
                or scan_unit not in chunk["display_text"]
            ):
                continue
            document = documents_by_id[parent_id]
            matches[(parent_id, chunk["chunk_id"])] = {
                "document_id": parent_id,
                "chunk_id": chunk["chunk_id"],
                "title": document["title"],
                "canonical_url": document["canonical_url"],
                "source_id": document["source_id"],
                "published_at": document.get("published_at"),
                "match_kind": (
                    "exact_span_in_other_current_document"
                    if scan_unit == evidence_span
                    else "exact_answer_unit_in_other_current_document"
                ),
            }
    else:
        subject_cell = _table_subject_cell(table_fact["row_text"])
        for candidate in table_facts:
            parent_id = candidate["parent_document_id"]
            if (
                parent_id == document_id
                or parent_id not in current_document_ids
                or candidate["attribute"] != table_fact["attribute"]
                or candidate["value"] != table_fact["value"]
                or _table_subject_cell(candidate["row_text"]) != subject_cell
            ):
                continue
            document = documents_by_id[parent_id]
            matches[(parent_id, candidate["source_chunk_id"])] = {
                "document_id": parent_id,
                "chunk_id": candidate["source_chunk_id"],
                "fact_id": candidate["fact_id"],
                "title": document["title"],
                "canonical_url": document["canonical_url"],
                "source_id": document["source_id"],
                "published_at": document.get("published_at"),
                "match_kind": "same_table_subject_attribute_value_in_other_current_document",
            }
    return [matches[key] for key in sorted(matches)]


def _prior_parent_ids(
    prior_sets: list[list[dict[str, Any]]], chunks_by_id: dict[str, dict[str, Any]]
) -> set[str]:
    parents: set[str] = set()
    for rows in prior_sets:
        for row in rows:
            for group in row.get("evidence_groups", []):
                for chunk_id in group.get("acceptable_chunk_ids", []):
                    chunk = chunks_by_id.get(chunk_id)
                    if chunk:
                        parents.add(chunk["parent_document_id"])
    return parents


def build_candidates(
    plan_rows: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    table_facts: list[dict[str, Any]],
    previous_packet: list[dict[str, Any]],
    prior_sets: list[list[dict[str, Any]]],
    *,
    plan_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    documents_by_id = {row["document_id"]: row for row in documents}
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    previous_by_ordinal = {row["slot_ordinal"]: row for row in previous_packet}
    current_document_ids = {
        row["document_id"]
        for row in documents
        if row.get("default_exposure") is True
        and row.get("status") in {"current", "active"}
    }
    prior_parents = _prior_parent_ids(prior_sets, chunks_by_id)
    chunks_by_parent: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        chunks_by_parent.setdefault(chunk["parent_document_id"], []).append(chunk)

    rows: list[dict[str, Any]] = []
    validated_particle_count = 0
    for slot in sorted(plan_rows, key=lambda row: row["slot_ordinal"]):
        source_id = slot["source_id"]
        stratum = slot["stratum"]
        base_key = "a" if stratum in {"positive_coordination_a", "single_requirement_control"} else "b"
        base = BASES[source_id][base_key]
        document = _resolve_prefix(documents, "document_id", base["document_prefix"])
        if document["source_id"] != source_id:
            raise RuntimeError(f"Source mismatch for slot {slot['slot_ordinal']}")
        fact_count = slot["expected_requirement_count"]
        facts = [dict(fact) for fact in base["facts"][:fact_count]]
        if len(facts) != fact_count:
            raise RuntimeError(f"Insufficient facts for slot {slot['slot_ordinal']}")
        if stratum == "single_requirement_control" and base.get(
            "single_control_evidence_spans"
        ):
            for fact, evidence_span in zip(
                facts, base["single_control_evidence_spans"], strict=True
            ):
                fact["evidence_span"] = evidence_span
                fact.pop("table_atomic_attribute", None)
                fact.pop("table_row_text", None)
        requirements = [
            _build_requirement(fact, base["entity"], ordinal)
            for ordinal, fact in enumerate(facts, 1)
        ]
        question = _question_for(base, stratum)
        validated_particle_count += len(validate_particle_tokens(_kiwi().tokenize(question)))
        surface = extract_entity_coordinated_surfaces(question, requirements)
        actual_action = "apply" if surface is not None else "bypass"

        evidence_groups = []
        duplicate_current_evidence = []
        for ordinal, fact in enumerate(facts, 1):
            table_fact = None
            exact_chunk = None
            if fact.get("exact_chunk_id"):
                exact_chunk = chunks_by_id.get(fact["exact_chunk_id"])
                if exact_chunk is None:
                    raise RuntimeError(
                        f"Exact source chunk missing: {fact['exact_chunk_id']}"
                    )
                if exact_chunk["parent_document_id"] != document["document_id"]:
                    raise RuntimeError(
                        f"Exact source chunk parent mismatch: {fact['exact_chunk_id']}"
                    )
                start = fact["start_offset"]
                end = fact["end_offset"]
                if exact_chunk["display_text"][start:end] != fact["evidence_span"]:
                    raise RuntimeError(
                        "Exact chunk offset mismatch: "
                        f"chunk={fact['exact_chunk_id']} start={start} end={end}"
                    )
                matching_chunks = [exact_chunk]
            elif fact.get("table_atomic_attribute"):
                table_fact = _resolve_table_atomic_fact(
                    fact, document["document_id"], table_facts
                )
                source_chunk = chunks_by_id.get(table_fact["source_chunk_id"])
                if source_chunk is None:
                    raise RuntimeError(
                        f"Atomic source chunk missing: {table_fact['source_chunk_id']}"
                    )
                start = table_fact["value_start_offset"]
                end = table_fact["value_end_offset"]
                if source_chunk["display_text"][start:end] != fact["evidence_span"]:
                    raise RuntimeError(
                        "Atomic value offset mismatch: "
                        f"fact={table_fact['fact_id']} start={start} end={end}"
                    )
                matching_chunks = [source_chunk]
            else:
                matching_chunks = [
                    chunk
                    for chunk in chunks_by_parent.get(document["document_id"], [])
                    if fact["evidence_span"] in chunk["display_text"]
                ]
            if not matching_chunks:
                raise RuntimeError(
                    f"Exact evidence missing: slot={slot['slot_ordinal']} span={fact['evidence_span']}"
                )
            evidence_group = {
                "group_id": f"evidence_{ordinal}",
                "requirement_id": f"requirement_{ordinal}",
                "evidence_span": fact["evidence_span"],
                "acceptable_chunk_ids": sorted(
                    chunk["chunk_id"] for chunk in matching_chunks
                ),
                "document_ids": [document["document_id"]],
                "expected_evidence": [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "parent_document_id": document["document_id"],
                        "title": document["title"],
                        "canonical_url": document["canonical_url"],
                        "source_id": source_id,
                        "status": document["status"],
                        "default_exposure": document["default_exposure"],
                        "display_text": chunk["display_text"],
                    }
                    for chunk in matching_chunks
                ],
            }
            if table_fact is not None:
                evidence_group["evidence_locator"] = {
                    "kind": "table_atomic_value_cell",
                    "fact_id": table_fact["fact_id"],
                    "source_chunk_id": table_fact["source_chunk_id"],
                    "table_id": table_fact["table_id"],
                    "row_id": table_fact["row_id"],
                    "attribute": table_fact["attribute"],
                    "start_offset": table_fact["value_start_offset"],
                    "end_offset": table_fact["value_end_offset"],
                }
            elif exact_chunk is not None:
                evidence_group["evidence_locator"] = {
                    "kind": "chunk_exact_slice",
                    "source_chunk_id": exact_chunk["chunk_id"],
                    "start_offset": fact["start_offset"],
                    "end_offset": fact["end_offset"],
                }
            evidence_groups.append(evidence_group)

            duplicate_matches = _duplicate_current_matches(
                evidence_span=fact["evidence_span"],
                source_display_text=matching_chunks[0]["display_text"],
                document_id=document["document_id"],
                current_document_ids=current_document_ids,
                documents_by_id=documents_by_id,
                chunks=chunks,
                table_fact=table_fact,
                table_facts=table_facts,
            )
            if duplicate_matches:
                duplicate_current_evidence.append(
                    {
                        "group_id": f"evidence_{ordinal}",
                        "evidence_span": fact["evidence_span"],
                        "scan_unit": (
                            fact["evidence_span"]
                            if table_fact is not None
                            else _duplicate_scan_unit(
                                fact["evidence_span"],
                                matching_chunks[0]["display_text"],
                            )
                        ),
                        "matches": duplicate_matches,
                    }
                )

        exception = None
        if document["document_id"] in prior_parents:
            if source_id == "dnf_account_policy":
                exception = "single_current_policy_parent_claim_level_review_required"
            elif source_id == "dnf_monthly_item":
                exception = "single_current_monthly_parent_claim_level_review_required"
            else:
                raise RuntimeError(
                    f"Unexpected prior parent overlap: {source_id} {document['document_id']}"
                )

        identity = _canonical_json_bytes(
            {
                "plan_sha256": plan_sha256,
                "slot_id": slot["slot_id"],
                "question": question,
                "requirements": requirements,
                "evidence_groups": evidence_groups,
            }
        )
        row = dict(slot)
        row.update(
            {
                "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
                "candidate_id": f"requirement_surface_candidate_sha256_{_sha256_bytes(identity)}",
                "question_text": question,
                "requirements": requirements,
                "evidence_groups": evidence_groups,
                "gold_answer": "\n".join(
                    dict.fromkeys(fact["evidence_span"] for fact in facts)
                ),
                "gold_chunk_ids": sorted(
                    {
                        chunk_id
                        for group in evidence_groups
                        for chunk_id in group["acceptable_chunk_ids"]
                    }
                ),
                "gold_document_ids": [document["document_id"]],
                "canonical_url": document["canonical_url"],
                "title": document["title"],
                "status": document["status"],
                "default_exposure": document["default_exposure"],
                "as_of": "2026-07-22",
                "time_scope": "current",
                "actual_surface_query_action_from_authored_requirements": actual_action,
                "surface_query_preview": surface,
                "duplicate_current_evidence": duplicate_current_evidence,
                "sibling_review_required": bool(duplicate_current_evidence),
                "duplicate_resolution": (
                    "question_scoped_to_2026-03-26_gold_unchanged"
                    if slot["slot_ordinal"] in {1, 3}
                    else (
                        "previous_special_gift_match_rejected_not_equivalent_unrelated_event_boilerplate"
                        if slot["slot_ordinal"] == 12
                        else (
                            "human_review_required_before_acceptable_sibling_application"
                            if duplicate_current_evidence
                            else None
                        )
                    )
                ),
                "parent_disjoint_from_prior_sets": document["document_id"] not in prior_parents,
                "parent_disjointness_exception_reason": exception,
                "authorship": "codex_authored_user_full_review_required",
                "human_review_decision": None,
                "human_reviewer_id": None,
                "human_reviewed_at": None,
                "human_review_rationale": None,
                "sealed_scoring_allowed": False,
            }
        )
        if base.get("reviewed_temporal_metadata"):
            row.update(base["reviewed_temporal_metadata"])
        rows.append(row)

    if set(previous_by_ordinal) != set(range(1, 33)):
        raise RuntimeError("Previous packet must contain exactly slot ordinals 1..32")
    changed_protected_slots = {
        row["slot_ordinal"]
        for row in rows
        if any(
            row[field] != previous_by_ordinal[row["slot_ordinal"]][field]
            for field in PROTECTED_APPROVED_FIELDS
        )
    }

    exact_questions = [_normalized(row["question_text"]) for row in rows]
    source_counts = Counter(row["source_id"] for row in rows)
    action_counts = Counter(row["actual_surface_query_action_from_authored_requirements"] for row in rows)
    exceptions = [
        row["candidate_id"]
        for row in rows
        if row["parent_disjointness_exception_reason"]
    ]
    gates = {
        "row_count_32": len(rows) == 32,
        "source_balance_4_each": set(source_counts.values()) == {4},
        "question_unique_32": len(set(exact_questions)) == 32,
        "expected_action_matches_32": all(
            row["expected_surface_query_action"]
            == row["actual_surface_query_action_from_authored_requirements"]
            for row in rows
        ),
        "apply_16_bypass_16": action_counts == {"apply": 16, "bypass": 16},
        "exact_evidence_present_32": all(
            group["acceptable_chunk_ids"]
            for row in rows
            for group in row["evidence_groups"]
        ),
        "multi_requirement_distinct_spans": all(
            len({group["evidence_span"] for group in row["evidence_groups"]})
            == len(row["requirements"])
            for row in rows
            if len(row["requirements"]) > 1
        ),
        "korean_particle_validation_32": len(rows) == 32,
        "current_document_duplicate_scan_32": all(
            "duplicate_current_evidence" in row
            and "sibling_review_required" in row
            for row in rows
        ),
        "approved_31_protected_fields_unchanged": all(
            row["slot_ordinal"] in REVIEW_REJECTED_SLOT_ORDINALS
            or all(
                row[field] == previous_by_ordinal[row["slot_ordinal"]][field]
                for field in PROTECTED_APPROVED_FIELDS
            )
            for row in rows
        ),
        "review_rejected_ord12_is_only_protected_change": (
            changed_protected_slots == REVIEW_REJECTED_SLOT_ORDINALS
        ),
        "parent_overlap_exceptions_policy_monthly_only": all(
            row["source_id"] in {"dnf_account_policy", "dnf_monthly_item"}
            for row in rows
            if row["parent_disjointness_exception_reason"]
        ),
        "human_review_pending_32": all(
            row["human_review_decision"] is None for row in rows
        ),
        "all_execution_and_training_flags_false_32": all(
            not row["sealed_scoring_allowed"]
            and not row["final_benchmark_eligible"]
            and not row["independent_holdout_claim_allowed"]
            and not row["training_allowed"]
            for row in rows
        ),
    }
    audit = {
        "gates": gates,
        "gate_pass": all(gates.values()),
        "source_counts": dict(sorted(source_counts.items())),
        "actual_action_counts": dict(sorted(action_counts.items())),
        "parent_disjoint_count": sum(
            row["parent_disjoint_from_prior_sets"] for row in rows
        ),
        "parent_overlap_exception_row_count": len(exceptions),
        "parent_overlap_exception_candidate_ids": exceptions,
        "validated_particle_token_count": validated_particle_count,
        "sibling_review_flagged_row_count": sum(
            row["sibling_review_required"] for row in rows
        ),
        "sibling_review_flagged_slot_ordinals": [
            row["slot_ordinal"] for row in rows if row["sibling_review_required"]
        ],
        "changed_protected_slot_ordinals": sorted(changed_protected_slots),
        "protected_approved_slot_ordinals": sorted(
            set(range(1, 33)) - REVIEW_REJECTED_SLOT_ORDINALS
        ),
        "independence_level": "paired_metamorphic_authored_canary_user_review_pending",
    }
    return rows, audit


def freeze_candidates(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {
        "builder_source": root / DEFAULT_SOURCE,
        "korean_particles_source": root / DEFAULT_PARTICLE_SOURCE,
        "refreeze_amendment": root / DEFAULT_AMENDMENT,
        "plan": root / DEFAULT_PLAN,
        "contract_manifest": root / DEFAULT_CONTRACT_MANIFEST,
        "documents": root / DEFAULT_DOCUMENTS,
        "chunks": root / DEFAULT_CHUNKS,
        "table_atomic_facts": root / DEFAULT_TABLE_FACTS,
        "previous_candidate_packet": root / DEFAULT_PREVIOUS_PACKET,
        "adaptive_dev_for_disjointness": root / DEFAULT_DEV,
        "downgraded_canary_for_disjointness": root / DEFAULT_DOWNGRADED_CANARY,
        "authored_validation_for_disjointness": root / DEFAULT_AUTHORED_VALIDATION,
    }
    missing = [name for name, path in inputs.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing authored surface canary inputs: {missing}")
    before = {name: file_sha256(path) for name, path in inputs.items()}
    rows, audit = build_candidates(
        read_jsonl(inputs["plan"]),
        read_jsonl(inputs["documents"]),
        read_jsonl(inputs["chunks"]),
        read_jsonl(inputs["table_atomic_facts"]),
        read_jsonl(inputs["previous_candidate_packet"]),
        [
            read_jsonl(inputs["adaptive_dev_for_disjointness"]),
            read_jsonl(inputs["downgraded_canary_for_disjointness"]),
            read_jsonl(inputs["authored_validation_for_disjointness"]),
        ],
        plan_sha256=before["plan"],
    )
    if not audit["gate_pass"]:
        raise RuntimeError(f"Authored surface canary audit failed: {audit['gates']}")

    payload = _serialize_jsonl(rows, lambda row: row["slot_ordinal"])
    payload_sha = _sha256_bytes(payload)
    packet_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_candidate_{payload_sha}.jsonl"
    )
    write_immutable(packet_path, payload)

    manifest = {
        "manifest_schema_version": "requirement-surface-query-authored-candidate-manifest-v1.2",
        "builder_version": BUILDER_VERSION,
        "inputs": {
            name: {"path": _relative(root, path), "sha256": before[name]}
            for name, path in inputs.items()
        },
        "candidate_packet": {
            "path": _relative(root, packet_path),
            "sha256": payload_sha,
            "row_count": len(rows),
        },
        "audit": audit,
        "state": {
            "authorship": "codex_authored_user_full_review_required",
            "previous_user_review": "31_APPROVED_1_REJECTED_ORD12",
            "previous_packet_preserved": True,
            "human_review": "PENDING_32",
            "independent_holdout_claim_allowed": False,
            "sealed_scoring_allowed": False,
            "runtime_or_canonical_promotion_allowed": False,
        },
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    manifest_path = root / "data/v3/evaluation" / (
        f"requirement_surface_query_canary_candidate_manifest_{manifest_sha}.json"
    )
    write_immutable(manifest_path, manifest_bytes)

    report = {
        "report_schema_version": "requirement-surface-query-authored-candidate-report-v1.2",
        "builder_version": BUILDER_VERSION,
        "candidate_packet_sha256": payload_sha,
        "manifest_sha256": manifest_sha,
        "audit": audit,
        "decisions": {
            "candidate_refreeze": "GO",
            "previous_packet_and_reports": "PRESERVED",
            "user_full_review": "PENDING",
            "immutable_reviewed_export": "NO_GO",
            "sealed_execution": "NO_GO",
            "runtime_or_canonical_promotion": "NO_GO",
        },
        "new_scoring_performed": False,
    }
    report_bytes = _canonical_json_bytes(report)
    report_sha = _sha256_bytes(report_bytes)
    report_path = root / "reports/v3" / (
        f"requirement_surface_query_canary_candidate_{report_sha}.json"
    )
    write_immutable(report_path, report_bytes)

    for name, path in inputs.items():
        if file_sha256(path) != before[name]:
            raise RuntimeError(f"Input changed while building authored canary: {name}")
    return {
        "candidate_packet_path": str(packet_path),
        "candidate_packet_sha256": payload_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "report_path": str(report_path),
        "report_sha256": report_sha,
        "audit": audit,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(freeze_candidates(root=args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
