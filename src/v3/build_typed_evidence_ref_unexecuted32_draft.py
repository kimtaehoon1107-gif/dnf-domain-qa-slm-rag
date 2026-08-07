from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl


BUILDER_VERSION = "typed-evidence-ref-unexecuted32-draft-builder-v2"
PACKET_SCHEMA_VERSION = "typed-evidence-ref-generalization-candidate-v1"
AS_OF = "2026-07-22"
PARENT_OVERLAP_NOTE = (
    "동일 공식 parent가 기존 개발 평가에 노출되었을 수 있으나, 이 문항의 질문과 "
    "claim은 신규 작성되었으며 검색·생성 실행 전 사람 검수로 claim-disjoint 여부를 확인합니다."
)


def requirement(
    requirement_id: str,
    subject: str,
    relation: str,
    value_type: str,
    required_values: list[Any],
    evidence_needles: list[str],
    *,
    expected_status: str = "supported",
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "subject": subject,
        "relation": relation,
        "value_type": value_type,
        "required_values": required_values,
        "evidence_needles": evidence_needles,
        "expected_status": expected_status,
    }


def case(
    source_id: str,
    primary_dimension: str,
    document_id: str,
    question_text: str,
    requirements: list[dict[str, Any]],
    *,
    time_scope: str = "current",
    expected_response_mode: str = "full_answer",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "primary_dimension": primary_dimension,
        "document_id": document_id,
        "question_text": question_text,
        "time_scope": time_scope,
        "expected_response_mode": expected_response_mode,
        "requirements": requirements,
    }


SPECS = [
    # dnf_notice
    case(
        "dnf_notice",
        "temporal_role",
        "document_sha256_16c3f563d11ad0d939df884d19e2bf1f0209abbde08acd7b3f869d5a0c60c605",
        "2026년 7월 16일 정기점검은 몇 시부터 몇 시까지 진행됐어?",
        [
            requirement(
                "maintenance_time",
                "2026년 7월 16일 정기점검",
                "maintenance_time",
                "date_range",
                ["04:30", "10:00"],
                ["| 시간 | 04:30 ~ 10:00 |"],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "boolean_direction",
        "document_sha256_9d68cc4b062748036699db69ce56459e6464f89718d7eddc71b36981766cb741",
        "7월 16일 일부 캐릭터 스킬 사용 시 화면 오류는 클라이언트 패치로 수정됐어?",
        [
            requirement(
                "fixed",
                "일부 캐릭터 스킬 사용 시 게임 화면 오류",
                "is_fixed",
                "boolean",
                [True],
                [
                    "* 일부 캐릭터의 스킬 사용 시 게임 화면이 비정상적으로 표시되는 현상\n"
                    "※ 오류 확인중에 있으며 추후 공지사항을 통해 안내 드리겠습니다.\n"
                    "※ 15시 6분경 클라이언트 패치로 수정되었습니다."
                ],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "multi_requirement",
        "document_sha256_0d05f0e9aa6f69ecea6f4aeca64f1adbb2a80f24a2284729bd4aab03c640a516",
        "토스페이 계좌·머니 할인 이벤트의 최소 결제금액과 즉시 할인액은 각각 얼마야?",
        [
            requirement(
                "minimum_payment",
                "토스페이 계좌·머니 할인 이벤트",
                "minimum_payment",
                "currency",
                [{"amount": 50000, "unit": "원"}],
                ["■ 이벤트 내용: 토스페이 계좌/머니로 5만원 이상 결제 시 2천원 즉시 할인"],
            ),
            requirement(
                "discount_amount",
                "토스페이 계좌·머니 할인 이벤트",
                "discount_amount",
                "currency",
                [{"amount": 2000, "unit": "원"}],
                ["■ 이벤트 내용: 토스페이 계좌/머니로 5만원 이상 결제 시 2천원 즉시 할인"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "unsupported_or_partial",
        "document_sha256_69d168ecc0027ce0a62c6cdb4dcfe015b877fc63967c4612c1c998601255d04e",
        "원격지원서비스는 7월 17일에 휴무였는지와 다음 정상 운영 시각을 알려줘.",
        [
            requirement(
                "closure_date",
                "원격지원서비스",
                "closure_date",
                "date",
                ["2026-07-17"],
                ["▒ 원격지원서비스 휴무 일정\n- 7/17(금) 제헌절"],
            ),
            requirement(
                "reopening_at",
                "원격지원서비스",
                "reopening_at",
                "datetime",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        time_scope="historical",
        expected_response_mode="partial_answer",
    ),
    # dnf_update
    case(
        "dnf_update",
        "direct_fact",
        "document_sha256_0062a3fc15ed594f3b0ddcf243aac93addb0f8c4b452ad4c8f6c8c2134f4e910",
        "7월 2일 업데이트에서 주간 길드원 랭킹 제외 기준은 며칠 미접속이었어?",
        [
            requirement(
                "inactivity_days",
                "주간 길드원 랭킹",
                "inactivity_days_for_ranking_exclusion",
                "number",
                [14],
                ["14일간 미접속 시, 주간 길드원 랭킹에서 제외되도록 변경됩니다."],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "sibling_relation",
        "document_sha256_02c3b128896e1e3040f725af3ad4831e517a42efb2a5dfbde6bea828efd7f78c",
        "7월 16일 캐릭터 밸런스 패치에서 검귀와 스트라이커(남)의 공격력 증가율은 각각 얼마야?",
        [
            requirement(
                "ghostblade_attack_increase",
                "검귀",
                "attack_increase",
                "percentage",
                [10.3],
                ["## 검귀\n기본 공격 및 전직 계열 스킬 공격력이 10.3% 증가합니다."],
            ),
            requirement(
                "male_striker_attack_increase",
                "스트라이커(남)",
                "attack_increase",
                "percentage",
                [11.7],
                ["## 스트라이커(남)\n기본 공격 및 전직 계열 스킬 공격력이 11.7% 증가합니다."],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "table_attribute",
        "document_sha256_45e66cd9ad5b868f3249e626f9e9bd01cf8fa98f8594e6a2ab64d7237aadb8cc",
        "검은 재앙 1개 상자(초월의 의지)의 판매 가격과 구매 제한은 뭐야?",
        [
            requirement(
                "price",
                "검은 재앙 1개 상자(초월의 의지)",
                "price",
                "currency",
                [{"amount": 50, "unit": "초월의 의지"}],
                [
                    "| 검은 재앙 1개 상자(초월의 의지) | 사용 시 검은 재앙 1개를 획득할 수 있습니다. "
                    "| 계정귀속 | 초월의 의지 50개 | 계정당 주 10회 |"
                ],
            ),
            requirement(
                "purchase_limit",
                "검은 재앙 1개 상자(초월의 의지)",
                "purchase_limit",
                "text",
                ["계정당 주 10회"],
                [
                    "| 검은 재앙 1개 상자(초월의 의지) | 사용 시 검은 재앙 1개를 획득할 수 있습니다. "
                    "| 계정귀속 | 초월의 의지 50개 | 계정당 주 10회 |"
                ],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "revision_selection",
        "document_sha256_2d0a6a7eaa670f1a9ec3a228a6942330b920e30ef0d3c8b5451b9e1400db9b2c",
        "5/21(목) 정기점검 업데이트 공지는 언제 게시됐고, 실제 점검 적용은 언제야?",
        [
            requirement(
                "posted_at",
                "5/21(목) 정기점검 업데이트 공지",
                "posted_at",
                "datetime",
                ["2026-05-20T15:00:00+09:00"],
                ["2026.05.20 15:00"],
            ),
            requirement(
                "effective_date",
                "5/21(목) 정기점검 업데이트",
                "effective_at",
                "date",
                ["2026-05-21"],
                ["5/21(목) 정기점검 업데이트 안내"],
            )
        ],
        time_scope="historical",
    ),
    # dnf_event
    case(
        "dnf_event",
        "temporal_role",
        "document_sha256_75ef9e30f89c30206aa42e2b905f8e60748b5779f2e2d4f598b348dedee35f93",
        "열대야를 날려줄 PC방 이벤트는 언제부터 언제까지 진행됐어?",
        [
            requirement(
                "event_period",
                "열대야를 날려줄 PC방",
                "event_period",
                "date_range",
                ["2026-07-09", "2026-08-06"],
                ["이벤트 기간 : 2026년 7월 9일(목) 점검 후 ~ 8월 6일(목) 점검 전"],
            )
        ],
    ),
    case(
        "dnf_event",
        "table_attribute",
        "document_sha256_75ef9e30f89c30206aa42e2b905f8e60748b5779f2e2d4f598b348dedee35f93",
        "[PC방]행운의 상자의 확정 기본 구성품은 뭐야?",
        [
            requirement(
                "guaranteed_component",
                "[PC방]행운의 상자",
                "guaranteed_component",
                "entity",
                ["[PC방]신비한 열쇠 꾸러미 1개"],
                ["| 기본 구성품 |\n| [PC방]신비한 열쇠 꾸러미 1개 |"],
            )
        ],
    ),
    case(
        "dnf_event",
        "multi_requirement",
        "document_sha256_99aa59034b47a44a9edd9855f25cf3eb930ba8edb04eef390cf1fc497f51a784",
        "레미디아 여프료시카 이벤트의 주간 초기화 시각과 미사용 보상 삭제 시각은 언제야?",
        [
            requirement(
                "weekly_reset_at",
                "레미디아 여프료시카 이벤트",
                "weekly_reset_at",
                "text",
                ["매주 목요일 06시"],
                ["- 주간 보상과 누적 시간은 매주 목요일 06시 기준으로 초기화 됩니다."],
            ),
            requirement(
                "deletion_at",
                "레미디아 여프료시카 이벤트 보상",
                "deletion_at",
                "datetime",
                ["2026-07-30T06:00:00+09:00"],
                ["- 모든 보상은 미사용 시 2026년 7월 30일(목) 06시 일괄 삭제됩니다."],
            ),
        ],
    ),
    case(
        "dnf_event",
        "unsupported_or_partial",
        "document_sha256_b7588ad16693be67d569c9bbccf133a0de542bc47251d4545e4f6610c784e412",
        "마일리지샵 2026 시즌7에서 플레이로 얻을 수 있는 일일 최대 마일리지와 현재 남은 획득 가능량을 알려줘.",
        [
            requirement(
                "daily_cap",
                "마일리지샵 2026 시즌7 플레이 마일리지",
                "daily_cap",
                "number",
                [50],
                ["- 던전/레이드/결투장을 통해 획득 가능한 마일리지는 일일 최대 50M입니다."],
            ),
            requirement(
                "remaining_earnable",
                "마일리지샵 2026 시즌7 플레이 마일리지",
                "remaining_earnable",
                "number",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        expected_response_mode="partial_answer",
    ),
    # dnf_game_guide
    case(
        "dnf_game_guide",
        "boolean_direction",
        "document_sha256_b56ebafdc51548a4f193812826a5cd8b10ebfebabe03e11d60396555dd9b00ec",
        "새로 만든 캐릭터를 24시간이 지나기 전에 삭제할 수 있어?",
        [
            requirement(
                "deletable_before_24_hours",
                "새로 만든 캐릭터",
                "deletable_before_24_hours",
                "boolean",
                [False],
                ["생성한 캐릭터는 24시간이 지나야 삭제할 수 있다는 점을 주의해주세요."],
            )
        ],
    ),
    case(
        "dnf_game_guide",
        "sibling_relation",
        "document_sha256_055c7b10d2ca37d95045bb61edaabba36228339d085b9de2beaa7b97b1caa903",
        "큐브의 계약에서 흑색 큐브 조각과 흰색 큐브 조각은 무기에 각각 어떤 속성을 부여해?",
        [
            requirement(
                "black_cube_attribute",
                "흑색 큐브 조각",
                "weapon_attribute",
                "enum",
                ["암속성"],
                ["- 흑색 큐브 조각 : 30초 마다 무기에 암속성 부여"],
            ),
            requirement(
                "white_cube_attribute",
                "흰색 큐브 조각",
                "weapon_attribute",
                "enum",
                ["명속성"],
                ["- 흰색 큐브 조각 : 30초 마다 무기에 명속성 부여"],
            ),
        ],
    ),
    case(
        "dnf_game_guide",
        "direct_fact",
        "document_sha256_47660415c71f8cce81bcc4aacdf4a8542a0f4e100daa5e264f7649d2fa69c237",
        "간이 정비기에서 아이템 수리는 어느 메뉴에서 할 수 있어?",
        [
            requirement(
                "repair_menu",
                "간이 정비기",
                "repair_menu",
                "text",
                ["상점/수리 메뉴"],
                ["간이 정비기의 상점/수리 메뉴에서는 아이템을 수리할 수 있습니다."],
            )
        ],
    ),
    case(
        "dnf_game_guide",
        "multi_requirement",
        "document_sha256_4031c1cbc3007562627954ea11a2d01d3ce0753eea3aa03d6e79173ca8943b05",
        "캐릭터 기본 피로도와 프리미엄 PC방 추가 피로도는 각각 얼마야?",
        [
            requirement(
                "base_fatigue",
                "캐릭터 피로도",
                "base_fatigue",
                "number",
                [156],
                ["캐릭터당 156의 피로도가 제공되며 프리미엄 PC방에서는 78의 추가 피로도가 주어집니다."],
            ),
            requirement(
                "premium_pc_fatigue",
                "프리미엄 PC방 피로도",
                "additional_fatigue",
                "number",
                [78],
                ["캐릭터당 156의 피로도가 제공되며 프리미엄 PC방에서는 78의 추가 피로도가 주어집니다."],
            ),
        ],
    ),
    # dnf_faq
    case(
        "dnf_faq",
        "boolean_direction",
        "document_sha256_ffdf081364217637758e4ce3f56ebba31607bddd9749ce9f17f0ad0fedb46b0e",
        "가브리엘의 상점 등장 확률 개선(14%)은 1인 플레이로 진행해도 파티플레이와 동일하게 적용돼?",
        [
            requirement(
                "solo_play_probability_applies",
                "가브리엘의 상점 등장 확률 개선(14%)",
                "applies_to_solo_play",
                "boolean",
                [True],
                ["파티플레이 뿐만아니라, 1인 플레이 시에도 적용 됩니다!"],
            )
        ],
    ),
    case(
        "dnf_faq",
        "direct_fact",
        "document_sha256_cdeef319cd3794e8c933b677ca69507ae4260ca8a5f4eb2c98dc436932e6cb13",
        "지정PC 한 기기에 등록할 수 있는 계정은 최대 몇 개야?",
        [
            requirement(
                "max_accounts",
                "지정PC 한 기기",
                "max_registered_accounts",
                "number",
                [3],
                ["기기 당 계정은 최대 3개까지 등록 할 수 있습니다."],
            )
        ],
    ),
    case(
        "dnf_faq",
        "multi_requirement",
        "document_sha256_82c5e90aab1a3c8f48817e666610c2e6f7d173c4201e11907c9a7442477ed122",
        "과실복구는 어떤 버튼으로 신청해야 하며 일반 1:1 문의로 신청해도 진행돼?",
        [
            requirement(
                "application_button",
                "과실복구",
                "application_button",
                "entity",
                ["복구신청 접수하기"],
                [
                    "STEP.1) 과실복구 신청을 위해서는 [복구신청 접수하기] 버튼을 클릭해서 "
                    "문의해 주셔야 합니다."
                ],
            ),
            requirement(
                "general_inquiry_supported",
                "과실복구",
                "available_via_general_inquiry",
                "boolean",
                [False],
                ["1:1 문의 작성으로 신청하는 경우 복구가 진행되지 않으니"],
            ),
        ],
    ),
    case(
        "dnf_faq",
        "unsupported_or_partial",
        "document_sha256_8674a62877f7e48ed7e0281959eaebb88a9db7c464afb9f15055a1a8ce26fef0",
        "화면이 상단에 고정돼 Alt+Tab이 안 될 때 권장 조치와 문제가 발생한 정확한 디스코드 버전을 알려줘.",
        [
            requirement(
                "recommended_action",
                "던전앤파이터 화면 고정 및 Alt+Tab 문제",
                "recommended_action",
                "text",
                ["던전앤파이터의 게임 오버레이 활성화 해제"],
                [
                    "디스코드의 [사용자 설정 > 게임 오버레이]에서\n"
                    "던전앤파이터의 게임 오버레이 활성화를 해제하여 이용해 보시기 바랍니다."
                ],
            ),
            requirement(
                "discord_version",
                "던전앤파이터 화면 고정 및 Alt+Tab 문제",
                "affected_discord_version",
                "text",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        expected_response_mode="partial_answer",
    ),
    # dnf_account_policy
    case(
        "dnf_account_policy",
        "revision_selection",
        "document_sha256_c7b4d4825f1bd82bfbad1db55d678070653c9c3b81e7c68c534eb4e698c32ded",
        "현재 던전앤파이터 운영정책 시행일과, 그 직전(종전) 운영정책 시행일은 각각 언제야?",
        [
            requirement(
                "current_effective_date",
                "현재 던전앤파이터 운영정책",
                "effective_at",
                "date",
                ["2026-03-15"],
                ["본 운영정책은 2026년 3월 15일부터 시행합니다."],
            ),
            requirement(
                "previous_effective_date",
                "종전 던전앤파이터 운영정책",
                "previous_effective_at",
                "date",
                ["2025-11-01"],
                ["2025년 11월 1일부터 시행되던 종전의 운영정책은 본 운영정책으로 대체합니다."],
            ),
        ],
    ),
    case(
        "dnf_account_policy",
        "sibling_relation",
        "document_sha256_c7b4d4825f1bd82bfbad1db55d678070653c9c3b81e7c68c534eb4e698c32ded",
        "서비스 담당자 인권 침해의 1차 조치와 2차 조치는 각각 뭐야?",
        [
            requirement(
                "first_measure",
                "서비스 담당자 인권 침해",
                "first_offense_measure",
                "text",
                ["경고, 상담 중단"],
                ["| 서비스 담당자 인권 침해 | 경고, 상담 중단 | 3일 게임 이용제한 | 7일 게임 이용제한 |"],
            ),
            requirement(
                "second_measure",
                "서비스 담당자 인권 침해",
                "second_offense_measure",
                "text",
                ["3일 게임 이용제한"],
                ["| 서비스 담당자 인권 침해 | 경고, 상담 중단 | 3일 게임 이용제한 | 7일 게임 이용제한 |"],
            ),
        ],
    ),
    case(
        "dnf_account_policy",
        "boolean_direction",
        "document_sha256_c7b4d4825f1bd82bfbad1db55d678070653c9c3b81e7c68c534eb4e698c32ded",
        "던전앤파이터 회사가 고객에게 ID나 비밀번호 같은 개인정보를 물어봐?",
        [
            requirement(
                "asks_credentials",
                "던전앤파이터 회사",
                "asks_customer_credentials",
                "boolean",
                [False],
                [
                    "[3-1] 회사는 던전앤파이터 개인정보처리방침 및 관계 법령을 준수하며, "
                    "고객의 개인정보(ID, 비밀번호 등)를 묻지 않습니다."
                ],
            )
        ],
    ),
    case(
        "dnf_account_policy",
        "direct_fact",
        "document_sha256_c7b4d4825f1bd82bfbad1db55d678070653c9c3b81e7c68c534eb4e698c32ded",
        "채팅 관련 제재(욕설·성희롱 등)의 누적일은 최대 며칠까지 가능해?",
        [
            requirement(
                "max_cumulative_sanction_days",
                "채팅 관련 제재 누적일",
                "max_cumulative_days",
                "number",
                [30],
                ["제재 누적일은 최대 30일까지 가능합니다."],
            )
        ],
    ),
    # dnf_seria_shop
    case(
        "dnf_seria_shop",
        "table_attribute",
        "document_sha256_8f4860daf9e5590777d632d84cc0a45a69d04c9d32751969606026a421823e62",
        "[M]신비한 방어구 업그레이드권의 거래 타입과 구매 제한은 뭐야?",
        [
            requirement(
                "trade_type",
                "[M]신비한 방어구 업그레이드권",
                "trade_type",
                "enum",
                ["계정귀속"],
                [
                    "| 아이템명 | [M]신비한 방어구 업그레이드권 | [M]추억의 오라 아바타 상자 |\n"
                    "| 아이콘 | | ​ |\n"
                    "| 가격 | 350M | 500M |\n"
                    "| 거래타입 | 계정귀속 | 계정귀속 |"
                ],
            ),
            requirement(
                "purchase_limit",
                "[M]신비한 방어구 업그레이드권",
                "purchase_limit",
                "enum",
                ["무제한"],
                [
                    "| 아이템명 | [M]신비한 방어구 업그레이드권 | [M]추억의 오라 아바타 상자 |\n"
                    "| 아이콘 | | ​ |\n"
                    "| 가격 | 350M | 500M |\n"
                    "| 거래타입 | 계정귀속 | 계정귀속 |\n"
                    "| 구매제한 | 무제한 | 무제한 |"
                ],
            ),
        ],
    ),
    case(
        "dnf_seria_shop",
        "sibling_relation",
        "document_sha256_8f4860daf9e5590777d632d84cc0a45a69d04c9d32751969606026a421823e62",
        "[M]향상된 럭키 박스 1단계와 3단계의 가격은 각각 몇 M이야?",
        [
            requirement(
                "stage_1_price",
                "[M]향상된 럭키 박스 1단계",
                "mileage_price",
                "number",
                [100],
                [
                    "| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) "
                    "| [M] 향상된 럭키 박스 (3 단계 ) |\n"
                    "| 아이콘 | | | |\n"
                    "| 가격 | 100M | 120M | 150M |"
                ],
            ),
            requirement(
                "stage_3_price",
                "[M]향상된 럭키 박스 3단계",
                "mileage_price",
                "number",
                [150],
                [
                    "| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) "
                    "| [M] 향상된 럭키 박스 (3 단계 ) |\n"
                    "| 아이콘 | | | |\n"
                    "| 가격 | 100M | 120M | 150M |"
                ],
            ),
        ],
    ),
    case(
        "dnf_seria_shop",
        "temporal_role",
        "document_sha256_82911a61f24bf745ec4020a067cee679f19c320742f264ffe898bad4098a7817",
        "2026 아라드 패스 웨딩 아바타 콤보 상자의 판매 기간은 언제부터 언제까지야?",
        [
            requirement(
                "sale_period",
                "2026 아라드 패스 웨딩 아바타 콤보 상자",
                "sale_period",
                "date_range",
                ["2026-06-18", "2026-08-13"],
                [
                    "- 2026 년 06 월 18 일 점검 후부터 2026 년 08 월 13일 점검 전까지 "
                    "세라샵 > 패키지 > 전체 카테고리에서 만나보실 수 있습니다 ."
                ],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_seria_shop",
        "revision_selection",
        "document_sha256_06c565de28c5644374faf5bc29fda19ebb457b7c3d2b57f266e797490a28f130",
        "2026년 1월에 판매한 해방의 열쇠 100개 상자는 언제 삭제됐어?",
        [
            requirement(
                "deletion_at",
                "2026년 1월 해방의 열쇠 100개 상자",
                "deletion_at",
                "datetime",
                ["2026-01-22T06:00:00+09:00"],
                [
                    "| 아이템명 | 해방의 열쇠 100개 상자 |\n"
                    "| 아이콘 | |\n"
                    "| 상점판매가격 | 없음 |\n"
                    "| 거래타입 | 교환가능 |\n"
                    "| 툴팁 | 사용 시 해방의 열쇠 100개, 봉인된 자물쇠 34개를 획득할 수 있습니다. "
                    "해방의 열쇠는 교환불가, 기간 무제한 아이템입니다. |\n"
                    "| 삭제일자 | 2026년 1월 22일 06시 일괄삭제 |"
                ],
            )
        ],
        time_scope="historical",
    ),
    # dnf_monthly_item
    case(
        "dnf_monthly_item",
        "revision_selection",
        "document_sha256_aa29165b9617ffd053c975a270d8da5b25339a564f95cb7bf46604788b8baec8",
        "2026년 5월 이달의 아이템은 무엇이었어?",
        [
            requirement(
                "item_name",
                "2026년 5월 이달의 아이템",
                "item_name",
                "entity",
                ["고대의 바인드 큐브 8개 상자"],
                ["# [5월 이달의 아이템] : 고대의 바인드 큐브 8개 상자"],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_monthly_item",
        "temporal_role",
        "document_sha256_eed106bcc44a337e140b93fa9d513cb50bc7b009ec85cdcfa0eaed66a3e3055e",
        "[2월]스페셜 클론 레어 아바타 풀세트 상자는 언제 삭제됐어?",
        [
            requirement(
                "deletion_at",
                "[2월]스페셜 클론 레어 아바타 풀세트 상자",
                "deletion_at",
                "datetime",
                ["2026-03-12T06:00:00+09:00"],
                ["| 삭제일자 | 2026년 03월 12일 06시 일괄삭제 |"],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_monthly_item",
        "table_attribute",
        "document_sha256_338290e51c69950482caf6721a96dc773666983de03a6075d2af41e962c41285",
        "[3월]스페셜 클론 레어 아바타 풀세트 상자의 상점판매가격과 거래 타입은 뭐야?",
        [
            requirement(
                "shop_price",
                "[3월]스페셜 클론 레어 아바타 풀세트 상자",
                "shop_price",
                "currency",
                [{"amount": 40000000, "unit": "골드"}],
                [
                    "| 아이템명 | [3월]스페셜 클론 레어 아바타 풀세트 상자 |\n"
                    "| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |\n"
                    "| 상점판매가격 | 4,000만 골드 |"
                ],
            ),
            requirement(
                "trade_type",
                "[3월]스페셜 클론 레어 아바타 풀세트 상자",
                "trade_type",
                "enum",
                ["교환가능"],
                [
                    "| 아이템명 | [3월]스페셜 클론 레어 아바타 풀세트 상자 |\n"
                    "| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |\n"
                    "| 상점판매가격 | 4,000만 골드 |\n"
                    "| 거래타입 | 교환가능 |"
                ],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_monthly_item",
        "unsupported_or_partial",
        "document_sha256_359cfa4af7313b672a2c84dfe0d8182b03f1518be2babfcf4ccf131c049b57c2",
        "[4월]스페셜 클론 레어 아바타 풀세트 상자의 상점판매가격과 계정당 구매 제한을 알려줘.",
        [
            requirement(
                "shop_price",
                "[4월]스페셜 클론 레어 아바타 풀세트 상자",
                "shop_price",
                "currency",
                [{"amount": 40000000, "unit": "골드"}],
                [
                    "| 아이템명 | [4월]스페셜 클론 레어 아바타 풀세트 상자 |\n"
                    "| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |\n"
                    "| 상점판매가격 | 4,000만 골드 |"
                ],
            ),
            requirement(
                "purchase_limit",
                "[4월]스페셜 클론 레어 아바타 풀세트 상자",
                "purchase_limit",
                "text",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        time_scope="historical",
        expected_response_mode="partial_answer",
    ),
]


def stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_sha256_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_evidence_unit(
    chunks_by_document: dict[str, list[dict[str, Any]]],
    document: dict[str, Any],
    needle: str,
) -> dict[str, Any]:
    matches = []
    for chunk in chunks_by_document.get(document["document_id"], []):
        start = chunk["display_text"].find(needle)
        if start >= 0:
            matches.append((chunk, start))
    if not matches:
        raise RuntimeError(
            f"evidence not found in {document['document_id']} ({document['title']}): {needle!r}"
        )
    chunk, start = sorted(matches, key=lambda item: (item[0]["chunk_index"], item[1]))[0]
    return {
        "document_id": document["document_id"],
        "chunk_id": chunk["chunk_id"],
        "start_char": start,
        "end_char": start + len(needle),
        "text": needle,
        "source_id": document["source_id"],
        "title": document["title"],
        "canonical_url": document["canonical_url"],
        "document_status": document["status"],
    }


def make_slots() -> tuple[list[dict[str, Any]], str]:
    design = [
        {"slot_ordinal": index, "source_id": spec["source_id"], "primary_dimension": spec["primary_dimension"]}
        for index, spec in enumerate(SPECS, start=1)
    ]
    plan_sha256 = hashlib.sha256(
        json.dumps(design, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    slots = []
    for item in design:
        slot_identity = {"plan_sha256": plan_sha256, **item}
        slots.append(
            {
                "packet_schema_version": "typed-evidence-ref-generalization-review-packet-v1",
                "plan_sha256": plan_sha256,
                "slot_id": stable_id("typed_unexecuted32_slot", slot_identity),
                **item,
                "candidate_id": None,
                "question_text": None,
                "as_of": None,
                "time_scope": None,
                "expected_response_mode": None,
                "requirements": [],
                "parent_overlap_exception_reason": None,
                "author_status": "pending",
                "author_id": None,
                "review": {
                    "status": "pending",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "rationale": None,
                },
                "execution_allowed": False,
                "training_allowed": False,
                "evaluation_role": "authoring_slot_not_an_evaluation_case",
            }
        )
    return slots, plan_sha256


def build_rows(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if len(SPECS) != 32:
        raise RuntimeError(f"expected 32 specs, got {len(SPECS)}")
    documents_by_id = {document["document_id"]: document for document in documents}
    chunks_by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk["parent_document_id"], []).append(chunk)

    slots, plan_sha256 = make_slots()
    rows = []
    for slot, spec in zip(slots, SPECS, strict=True):
        document = documents_by_id.get(spec["document_id"])
        if document is None:
            raise RuntimeError(f"missing document: {spec['document_id']}")
        if document["source_id"] != spec["source_id"]:
            raise RuntimeError(
                f"source mismatch for {document['document_id']}: "
                f"{document['source_id']} != {spec['source_id']}"
            )
        requirements = []
        for item in spec["requirements"]:
            units = [
                find_evidence_unit(chunks_by_document, document, needle)
                for needle in item["evidence_needles"]
            ]
            requirements.append(
                {
                    "requirement_id": item["requirement_id"],
                    "subject": item["subject"],
                    "relation": item["relation"],
                    "value_type": item["value_type"],
                    "required_values": item["required_values"],
                    "acceptable_evidence_units": units,
                    "expected_status": item["expected_status"],
                }
            )
        identity = {
            "slot_id": slot["slot_id"],
            "question_text": spec["question_text"],
            "requirements": requirements,
        }
        rows.append(
            {
                **slot,
                "packet_schema_version": PACKET_SCHEMA_VERSION,
                "candidate_id": stable_id("typed_unexecuted32_candidate", identity),
                "question_text": spec["question_text"],
                "as_of": AS_OF,
                "time_scope": spec["time_scope"],
                "expected_response_mode": spec["expected_response_mode"],
                "requirements": requirements,
                "primary_document_id": document["document_id"],
                "primary_document_title": document["title"],
                "primary_document_url": document["canonical_url"],
                "parent_overlap_exception_reason": PARENT_OVERLAP_NOTE,
                "author_status": "draft_complete_pending_human_review",
                "author_id": "codex",
                "review": {
                    "status": "pending",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "rationale": None,
                },
                "execution_allowed": False,
                "training_allowed": False,
                "evaluation_role": "codex_authored_unexecuted_candidate_pending_human_review",
            }
        )
    return slots, rows, plan_sha256


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "slot_ordinal",
        "source_id",
        "primary_dimension",
        "question_text",
        "expected_response_mode",
        "primary_document_title",
        "primary_document_url",
        "requirements_json",
        "review_decision",
        "reviewer_id",
        "review_rationale",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "slot_ordinal": row["slot_ordinal"],
                    "source_id": row["source_id"],
                    "primary_dimension": row["primary_dimension"],
                    "question_text": row["question_text"],
                    "expected_response_mode": row["expected_response_mode"],
                    "primary_document_title": row["primary_document_title"],
                    "primary_document_url": row["primary_document_url"],
                    "requirements_json": json.dumps(
                        row["requirements"], ensure_ascii=False, separators=(",", ":")
                    ),
                    "review_decision": "",
                    "reviewer_id": "",
                    "review_rationale": "",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--slots-output", type=Path, required=True)
    parser.add_argument("--jsonl-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    outputs = (
        args.slots_output,
        args.jsonl_output,
        args.csv_output,
        args.manifest_output,
    )
    for output in outputs:
        if output.exists():
            raise RuntimeError(f"output already exists: {output}")

    slots, rows, plan_sha256 = build_rows(
        list(read_jsonl(args.documents)), list(read_jsonl(args.chunks))
    )
    write_jsonl(args.slots_output, slots)
    write_jsonl(args.jsonl_output, rows)
    write_review_csv(args.csv_output, rows)

    source_counts = Counter(row["source_id"] for row in rows)
    dimension_counts = Counter(row["primary_dimension"] for row in rows)
    manifest = {
        "builder_version": BUILDER_VERSION,
        "status": "draft_pending_human_review_execution_locked",
        "plan_sha256": plan_sha256,
        "row_count": len(rows),
        "requirement_count": sum(len(row["requirements"]) for row in rows),
        "pending_review_count": sum(row["review"]["status"] == "pending" for row in rows),
        "execution_allowed_rows": sum(row["execution_allowed"] for row in rows),
        "training_allowed_rows": sum(row["training_allowed"] for row in rows),
        "source_counts": dict(sorted(source_counts.items())),
        "dimension_counts": dict(sorted(dimension_counts.items())),
        "inputs": {
            "documents": {
                "path": args.documents.as_posix(),
                "sha256": sha256_path(args.documents),
            },
            "chunks": {
                "path": args.chunks.as_posix(),
                "sha256": sha256_path(args.chunks),
            },
        },
        "outputs": {
            "slots": {
                "path": args.slots_output.as_posix(),
                "sha256": sha256_path(args.slots_output),
            },
            "jsonl": {
                "path": args.jsonl_output.as_posix(),
                "sha256": sha256_path(args.jsonl_output),
            },
            "csv": {
                "path": args.csv_output.as_posix(),
                "sha256": sha256_path(args.csv_output),
            },
        },
        "retrieval_run_performed": False,
        "generation_run_performed": False,
        "evaluation_run_performed": False,
        "human_review_required_before_freeze": True,
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
