from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl, write_jsonl


BUILDER_VERSION = "typed-evidence-ref-generalization-candidate-builder-v1"
AS_OF = "2026-07-17"


def req(
    requirement_id: str,
    subject: str,
    relation: str,
    value_type: str,
    required_values: list[Any],
    evidence_needles: list[str],
    *,
    expected_status: str = "supported",
    document_suffix: str | None = None,
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "subject": subject,
        "relation": relation,
        "value_type": value_type,
        "required_values": required_values,
        "evidence_needles": evidence_needles,
        "expected_status": expected_status,
        "document_suffix": document_suffix,
    }


def case(
    source_id: str,
    primary_dimension: str,
    document_suffix: str,
    question_text: str,
    requirements: list[dict[str, Any]],
    *,
    time_scope: str = "current",
    expected_response_mode: str = "full_answer",
    parent_overlap_exception_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "primary_dimension": primary_dimension,
        "document_suffix": document_suffix,
        "question_text": question_text,
        "as_of": AS_OF,
        "time_scope": time_scope,
        "expected_response_mode": expected_response_mode,
        "requirements": requirements,
        "parent_overlap_exception_reason": parent_overlap_exception_reason,
    }


SPECS = [
    # dnf_notice
    case(
        "dnf_notice",
        "temporal_role",
        "2aae8f0b99",
        "2026년 세라 이용약관 개정안은 언제부터 적용돼?",
        [req("effective_date", "세라 이용약관 개정안", "effective_at", "date", ["2026-05-28"], ["▒ 적용 일자\n- 2026년 5월 28일(목)"])],
    ),
    case(
        "dnf_notice",
        "boolean_direction",
        "e44c4b6177",
        "4월 2일 확인된 오류 기준으로 조율의 경계에서 광휘의 의지를 열면 연출이 정상 출력됐어?",
        [
            req(
                "effect_rendered",
                "조율의 경계 - 광휘의 의지 개봉 연출",
                "is_normally_rendered",
                "boolean",
                [False],
                ["조율의 경계 - 광휘의 의지 개봉 시 연출이 출력되지 않는 현상"],
            )
        ],
    ),
    case(
        "dnf_notice",
        "sibling_relation",
        "22ba6f44cd",
        "세리아와 함께한 20주년 선물 5주차 추첨에서 그래픽카드와 키보드·장패드는 각각 몇 개였어?",
        [
            req("graphics_card_quantity", "[20th special]던전 앤 그래픽카드", "drawing_goods_quantity", "number", [4], ["[20th special]던전 앤 그래픽카드 (4개)"]),
            req("keyboard_mousepad_quantity", "[20th special]20주년 키보드 + 장패드", "drawing_goods_quantity", "number", [12], ["[20th special]20주년 키보드 + 장패드 (12개)"]),
        ],
    ),
    case(
        "dnf_notice",
        "multi_requirement",
        "a8a2c0c2e9",
        "Chrome 141 업데이트로 ISP 결제에 어떤 영향이 있었고, 권한 알림이 뜨면 어떻게 해야 했어?",
        [
            req(
                "payment_impact",
                "Chrome 141 업데이트",
                "payment_impact",
                "text",
                ["로컬 네트워크 접근이 기본 활성화로 변경되어 ISP 결제가 불가"],
                ["구글 크롬 브라우저 업데이트로 [로컬 네트워크 Local Network Access']이 기본 활성화로 변경되어 ISP 결제 불가"],
            ),
            req(
                "permission_action",
                "ISP 결제 로컬 네트워크 접근 알림",
                "recommended_action",
                "enum",
                ["허용"],
                ["로컬 네트워크 엑세스 허용/차단 알럿 발생 시, 허용 설정"],
            ),
        ],
    ),
    case(
        "dnf_notice",
        "table_attribute",
        "5d5d243c",
        "2026년 4월 2일 정기점검은 몇 시부터 몇 시까지였어?",
        [req("maintenance_time", "2026년 4월 2일 정기점검", "maintenance_time", "date_range", ["04:30", "10:00"], ["| 시간 | 04:30 ~ 10:00 |"])],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "revision_selection",
        "5ab627c51d",
        "2025년에 공지된 던전앤파이터 운영정책 변경은 언제 시행될 예정이었어?",
        [req("policy_effective_date", "던전앤파이터 운영정책 변경", "effective_at", "date", ["2025-11-01"], ["2025년 11월 1일 자로 변경이 예정"])],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "unsupported_or_partial",
        "e44c4b6177",
        "4월 2일 조율의 경계 연출 오류는 확인 중이었는지와 정확한 수정 완료 시각을 알려줘.",
        [
            req("investigation_status", "조율의 경계 연출 오류", "investigation_status", "enum", ["확인 중"], ["오류 확인중에 있으며 추후 공지사항을 통해 안내"]),
            req("fixed_at", "조율의 경계 연출 오류", "fixed_at", "datetime", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
    ),
    case(
        "dnf_notice",
        "direct_fact",
        "8033b142e6",
        "세리아의 특별 상점은 게임 안에서 어디서 찾을 수 있어?",
        [req("shop_location", "세리아의 특별 상점", "location", "text", ["세리아방의 NPC 세리아"], ["세리아방의 NPC 세리아를 클릭하면 찾을 수 있습니다."])],
    ),
    # dnf_update
    case(
        "dnf_update",
        "temporal_role",
        "30f479992f",
        "시즌 11 Act 2 '제국의 파도 & 폭권' 업데이트는 언제 적용됐어?",
        [req("effective_date", "시즌 11 Act 2. 제국의 파도 & 폭권", "effective_at", "date", ["2026-06-04"], ["6/4(목) 점검 중 업데이트 되는 내용"])],
    ),
    case(
        "dnf_update",
        "boolean_direction",
        "7610692c97",
        "7월 9일 업데이트에서 DirectX11의 높은 메모리 사용량 문제가 수정됐어?",
        [req("dx11_memory_fixed", "DirectX11 높은 메모리 사용량", "is_fixed", "boolean", [True], ["DirectX11 이용 시 DirectX9 대비 메모리 사용량이 높은 현상이 수정됩니다."])],
    ),
    case(
        "dnf_update",
        "sibling_relation",
        "7610692c97",
        "7월 9일 최적화 업데이트에서 던전 플레이 메모리와 DirectX11 메모리는 각각 어떻게 바뀌었어?",
        [
            req("dungeon_memory", "던전 플레이 메모리 사용량", "change", "enum", ["감소"], ["던전 플레이 과정에서 발생하는 일부 비정상적인 메모리 사용량이 감소합니다."]),
            req("dx11_memory", "DirectX11 메모리 사용량 문제", "change", "enum", ["수정"], ["DirectX11 이용 시 DirectX9 대비 메모리 사용량이 높은 현상이 수정됩니다."]),
        ],
    ),
    case(
        "dnf_update",
        "multi_requirement",
        "e900ccb3",
        "5월 28일 업데이트의 태초 소울 1개 상자는 광휘의 잔영 몇 개였고 월 구매 제한은 몇 회였어?",
        [
            req("price", "태초 소울 1개 상자", "price", "currency", [{"amount": 120, "unit": "광휘의 잔영"}], ["| 태초 소울 1개 상자 | 사용 시 태초 소울 1개를 획득할 수 있습니다. <구매 가능 횟수> - 월 4회 남은 구매 횟수는 최대 4회까지 다음달로 이월되어 적용됩니다. | 교환불가 | 광휘의 잔영 120개 | 계정당 월 4회 |"]),
            req("monthly_limit", "태초 소울 1개 상자", "purchase_limit", "number", [4], ["| 태초 소울 1개 상자 | 사용 시 태초 소울 1개를 획득할 수 있습니다. <구매 가능 횟수> - 월 4회 남은 구매 횟수는 최대 4회까지 다음달로 이월되어 적용됩니다. | 교환불가 | 광휘의 잔영 120개 | 계정당 월 4회 |"]),
        ],
    ),
    case(
        "dnf_update",
        "table_attribute",
        "e900ccb3",
        "5월 28일 업데이트에서 광휘의 잔영의 거래 타입은 뭐였어?",
        [req("trade_type", "광휘의 잔영", "trade_type", "enum", ["교환불가"], ["| 광휘의 잔영 | NPC 켈돈 자비 상점에서 다음 아이템 구매에 사용합니다. 태초 광휘의 의지 태초 소울 1개 상자 에픽 소울 1개 상자 영롱한 조율의 추 1개 상자 광휘의 잔영 1개 상자 (계정귀속) | 교환불가 |"])],
    ),
    case(
        "dnf_update",
        "revision_selection",
        "b0ce2a7f23",
        "시즌 11 Act 1 업데이트 공지는 어느 날짜 점검에 적용된다고 했어?",
        [req("effective_date", "시즌 11 Act 1", "effective_at", "date", ["2026-04-23"], ["4/23(목) 점검 중 업데이트 되는 내용"])],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "unsupported_or_partial",
        "7610692c97",
        "7월 9일 업데이트에서 DirectX11 메모리 문제의 수정 여부와 메모리 사용량 감소율을 알려줘.",
        [
            req("fixed", "DirectX11 높은 메모리 사용량", "is_fixed", "boolean", [True], ["DirectX11 이용 시 DirectX9 대비 메모리 사용량이 높은 현상이 수정됩니다."]),
            req("reduction_percentage", "DirectX11 메모리 사용량", "reduction_percentage", "percentage", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
    ),
    case(
        "dnf_update",
        "direct_fact",
        "7610692c97",
        "7월 9일 업데이트에서 디레지에 레이드 입장 시 무엇이 개선됐어?",
        [req("improvement", "디레지에 레이드 던전 입장", "improvement", "text", ["로딩 속도"], ["디레지에 레이드 - 던전 입장 시의 로딩 속도가 개선됩니다."])],
    ),
    # dnf_event
    case(
        "dnf_event",
        "temporal_role",
        "8040c31a09",
        "미라클의 해양 탐구 생활 이벤트 기간은 언제부터 언제까지야?",
        [req("event_period", "미라클의 해양 탐구 생활", "event_period", "date_range", ["2026-06-04", "2026-08-27"], ["이벤트 기간 : 2026년 6월 4일(목) 점검 후 ~ 8월 27일(목) 점검 전"])],
    ),
    case(
        "dnf_event",
        "boolean_direction",
        "5a16420689",
        "썸머 블라썸의 여름을 부탁해 이벤트 효과는 결투장에도 적용돼?",
        [req("applies_to_arena", "썸머 블라썸 이벤트 효과", "applies_to_duel_arena", "boolean", [False], ["결투장/위업의 기억/해방된 흉몽 챌린지/월드보스 : 감염지/디레지에 레이드/아포칼립스에서는 적용되지 않습니다."])],
    ),
    case(
        "dnf_event",
        "sibling_relation",
        "b73226afe888",
        "썸머 특제 피로도 30 회복의 비약은 1회차와 7회차에 각각 얼마였어?",
        [
            req("first_purchase_price", "[세라샵]2026 썸머 특제 피로도 30 회복의 비약 NO.1", "price", "currency", [{"amount": 500, "unit": "세라"}], ["| 1회차 | | [세라샵]2026 썸머 특제 피로도 30 회복의 비약 NO.1 | 500세라 |"]),
            req("seventh_purchase_price", "[세라샵]2026 썸머 특제 피로도 30 회복의 비약 NO.7", "price", "currency", [{"amount": 2000, "unit": "세라"}], ["| 7회차 | | [세라샵]2026 썸머 특제 피로도 30 회복의 비약 NO.7 | 2,000세라 |"]),
        ],
    ),
    case(
        "dnf_event",
        "multi_requirement",
        "c5ba3cc499",
        "미카엘라 프리뷰 방송은 언제 열리고, 어디에서 볼 수 있어?",
        [
            req("broadcast_at", "미카엘라 프리뷰 방송", "broadcast_at", "datetime", ["2026-07-25T19:00:00+09:00"], ["2026년 7월 25일(토) 오후 7시"]),
            req("channels", "미카엘라 프리뷰 방송", "broadcast_channels", "entity_list", ["넥슨 라이브", "던파TV"], ["넥슨 라이브", "YouTube 던파TV 채널에서도 동시 송출됩니다."]),
        ],
    ),
    case(
        "dnf_event",
        "table_attribute",
        "f28761ee1c",
        "파도 X 폭권 패키지의 '운명을 담는 재단사 플래티넘'은 공격력과 버프력을 각각 몇 퍼센트 증폭해?",
        [
            req("attack_amplification", "운명을 담는 재단사 플래티넘", "attack_amplification", "percentage", [40], ["공격력 증폭 +40% 버프력 증폭 +10%"]),
            req("buff_amplification", "운명을 담는 재단사 플래티넘", "buff_amplification", "percentage", [10], ["공격력 증폭 +40% 버프력 증폭 +10%"]),
        ],
    ),
    case(
        "dnf_event",
        "revision_selection",
        "29d2dbb888",
        "2026 나비 무도회 패키지에 포함되는 직업 아바타는 어느 날짜의 라이브 서버 업데이트를 기준으로 했어?",
        [req("class_cutoff", "2026 나비 무도회 직업 아바타", "revision_cutoff", "date", ["2026-05-28"], ["2026년 5월 28일 기준 라이브 서버 업데이트가 완료된 직업의 아바타만 포함"])],
        time_scope="historical",
    ),
    case(
        "dnf_event",
        "unsupported_or_partial",
        "d969020850",
        "넥플과 함께! 뉴 페이스! 핫 썸머! 이벤트 퀘스트 보상은 계정당 몇 번 받을 수 있고, 남은 보상 재고는 몇 개야?",
        [
            req("account_limit", "이벤트 퀘스트 보상", "account_receive_limit", "number", [1], ["이벤트 퀘스트 보상은 넥슨플레이에서 각 계정당 1회 받을 수 있습니다."]),
            req("remaining_stock", "이벤트 퀘스트 보상", "remaining_stock", "number", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
    ),
    case(
        "dnf_event",
        "direct_fact",
        "8e0b2bc048",
        "제국기사 X 인파이터(여) 특별 선물 쿠폰은 계정당 몇 번 입력할 수 있어?",
        [req("coupon_limit", "제국기사 X 인파이터(여) 특별 선물 쿠폰", "account_input_limit", "number", [1], ["쿠폰은 계정당 1회 입력 가능합니다."])],
    ),
    # dnf_game_guide
    case(
        "dnf_game_guide",
        "temporal_role",
        "09b10ce9e52e0c25",
        "던파ON 출석체크는 매일 몇 시에 갱신되고, 보상 교환의 1주 기준은 언제야?",
        [
            req("daily_reset_time", "던파ON 출석체크", "daily_reset_time", "enum", ["06:00"], ["출석체크는 매일 06시를 기준으로 갱신됩니다."]),
            req("weekly_reset_at", "던파ON 보상 교환", "weekly_reset_at", "enum", ["매주 목요일 오전 6시"], ["1주 기준은 매주 목요일 오전 6시"]),
        ],
    ),
    case(
        "dnf_game_guide",
        "boolean_direction",
        "24cde1942a",
        "다른 채널에 접속한 캐릭터에게 트레이드를 신청할 수 있어?",
        [req("cross_channel_trade", "트레이드", "can_request_cross_channel", "boolean", [False], ["다른 채널에 접속한 캐릭터에게는 트레이드를 신청할 수 없습니다."])],
    ),
    case(
        "dnf_game_guide",
        "sibling_relation",
        "24cde1942a",
        "트레이드 기본 수수료와 장비류 아이템의 추가 수수료는 각각 몇 퍼센트야?",
        [
            req("base_fee", "트레이드", "base_fee", "percentage", [3], ["트레이드 시에는 3%의 수수료가 부과됩니다."]),
            req("equipment_extra_fee", "장비류 아이템 트레이드", "additional_fee", "percentage", [2], ["장비류 아이템인 경우에는 2%의 수수료가 추가로 부과됩니다.(총 5%)"]),
        ],
    ),
    case(
        "dnf_game_guide",
        "multi_requirement",
        "06cd642fae",
        "인형사 전문직업을 선택하려면 캐릭터 레벨과 무색 큐브 조각이 각각 얼마나 필요해?",
        [
            req("required_level", "인형사 전문직업", "required_character_level", "number", [20], ["캐릭터 20레벨을 달성하면"]),
            req("cube_quantity", "인형사 전문직업", "required_colorless_cube_fragments", "number", [100], ["무색 큐브 조각 100개를 가져가면"]),
        ],
    ),
    case(
        "dnf_game_guide",
        "table_attribute",
        "fb22fb75c0",
        "화면 설명의 ② 항목은 무엇을 보여주고 어떤 키로 조작해?",
        [
            req("displayed_information", "화면 설명 ②", "displayed_information", "text", ["캐릭터에게 적용 중인 효과"], ["| ② | 캐릭터에게 적용되고 있는 효과"]),
            req("control_keys", "화면 설명 ②", "control_keys", "text", ["키보드 1~6"], ["키보드 1~6"]),
        ],
    ),
    case(
        "dnf_game_guide",
        "revision_selection",
        "4935864db0",
        "현재 장비 시뮬레이터 가이드에서 지원하는 장비 레벨은 무엇이야?",
        [req("supported_levels", "장비 시뮬레이터", "supported_equipment_levels", "entity_list", [110, 115], ["110레벨 장비 또는 115레벨 장비"])],
    ),
    case(
        "dnf_game_guide",
        "unsupported_or_partial",
        "03c3d73afc",
        "아바타는 총 몇 부위로 구성되고, 아바타 프리셋은 최대 몇 개까지 저장할 수 있어?",
        [
            req("part_count", "아바타", "part_count", "number", [11], ["오라, 총 11부위"]),
            req("preset_limit", "아바타 프리셋", "maximum_saved_presets", "number", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
    ),
    case(
        "dnf_game_guide",
        "direct_fact",
        "6044d248bd",
        "스킬별 제압력 수치는 어디에서 확인할 수 있어?",
        [req("location", "스킬별 제압력 수치", "lookup_location", "text", ["스킬 정보(툴팁)"], ["각 스킬의 제압력 수치는 스킬 정보(툴팁)에서 확인 가능합니다."])],
    ),
    # dnf_faq
    case(
        "dnf_faq",
        "temporal_role",
        "1141084058",
        "세라 아이템은 구매 후 며칠 이내에 청약철회할 수 있어?",
        [req("withdrawal_period", "세라 아이템 청약철회", "withdrawal_period_days", "number", [7], ["세라로 아이템을 구매 후 7일 이내에 구매를 취소할 수 있는 시스템"])],
    ),
    case(
        "dnf_faq",
        "boolean_direction",
        "2f76903847",
        "휴대폰이 정지되기 전에 모바일 OTP를 설치해 사용 중이었다면 정지 후에도 OTP를 쓸 수 있어?",
        [req("otp_after_suspension", "모바일 OTP", "usable_after_phone_suspension", "boolean", [True], ["정지된 이후에도 OTP 이용이 가능합니다."])],
    ),
    case(
        "dnf_faq",
        "sibling_relation",
        "839220188d",
        "히든 레어 아바타를 같은 계정 캐릭터와 다른 계정 캐릭터에게 넘길 때 교환불가 타입으로 바뀌는지 각각 알려줘.",
        [
            req("same_account_trade_type", "히든 레어 아바타 동일 계정 이동", "changes_to_untradeable", "boolean", [False], ["동일 계정 내 다른 캐릭터로 우편 이동 시에는\n거래타입이 교환불가 상태로 변경되지 않습니다."]),
            req("other_account_trade_type", "히든 레어 아바타 다른 계정 이동", "changes_to_untradeable", "boolean", [True], ["다른 계정으로의 이동(트레이드, 경매장, 아바타마켓 등)이 발생하면\n교환불가 타입으로 변경"]),
        ],
    ),
    case(
        "dnf_faq",
        "multi_requirement",
        "6c2b6ce340",
        "지정PC 등록과 삭제는 각각 어디에서 할 수 있어?",
        [
            req("registration_location", "지정PC", "registration_location", "enum", ["게임 내"], ["지정PC는 게임 내에서만 등록이 가능"]),
            req("deletion_location", "지정PC", "deletion_location", "entity_list", ["게임", "웹"], ["삭제는 게임 혹은 웹에서 진행할 수 있습니다."]),
        ],
    ),
    case(
        "dnf_faq",
        "table_attribute",
        "8ea6e92b0b",
        "은 금고의 저장 칸 수와 가격은 얼마야?",
        [
            req("slot_count", "은 금고", "slot_count", "number", [40], ["| 은 금고 | 40 칸 | 400 세라 |"]),
            req("price", "은 금고", "price", "currency", [{"amount": 400, "unit": "세라"}], ["| 은 금고 | 40 칸 | 400 세라 |"]),
        ],
    ),
    case(
        "dnf_faq",
        "revision_selection",
        "b0203b50ef",
        "고블린패드 신규 발급은 언제 중단됐고, 기존 이용자는 재발급할 수 있어?",
        [
            req("new_issue_stopped_at", "고블린패드 신규 발급", "stopped_at", "date", ["2020-06-25"], ["2020년 6월 25일 부로 중단되었습니다."]),
            req("reissue_existing_user", "고블린패드 기존 이용자", "can_reissue", "boolean", [True], ["기존 이용 중이신 경우 비밀번호 변경, 재발급이 가능합니다."]),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_faq",
        "unsupported_or_partial",
        "14e39b4d2172",
        "네이버 로그인 계정 이벤트 혜택 1·2의 Npay 포인트는 언제 적립되고, 정확히 몇 포인트가 적립돼?",
        [
            req("credit_timing", "네이버 로그인 계정 이벤트 혜택 1·2 Npay 포인트", "credited_after", "number", [7], ["결제완료 시점으로부터 7일 이후에 적립"]),
            req("credit_amount", "네이버 로그인 계정 이벤트 혜택 1·2 Npay 포인트", "credit_amount", "number", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
    ),
    case(
        "dnf_faq",
        "direct_fact",
        "9f22357028",
        "이벤트로 받은 세라 또는 넥슨 쿠폰은 어디에서 사용할 수 있어?",
        [req("redeem_location", "세라/넥슨 쿠폰", "redeem_location", "text", ["던전앤파이터 홈페이지"], ["세라/넥슨 쿠폰을 이용하시길 원하신다면\n던파ON이 아닌, 던전앤파이터 홈페이지를 이용해주세요."])],
    ),
    # dnf_account_policy
    case(
        "dnf_account_policy",
        "temporal_role",
        "e698c32ded",
        "현재 던전앤파이터 운영정책은 언제부터 시행됐어?",
        [req("effective_date", "던전앤파이터 운영정책", "effective_at", "date", ["2026-03-15"], ["본 운영정책은 2026년 3월 15일부터 시행합니다."])],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "boolean_direction",
        "e698c32ded",
        "버그를 발견한 고객이 제보하지 않고 다른 사람에게 퍼뜨려도 운영정책상 괜찮아?",
        [req("bug_spread_allowed", "버그 발견 고객", "may_spread_without_reporting", "boolean", [False], ["이 의무를 다하지 않고 버그를 악용하거나 타인에게 전파하는 경우 게임이용에 제한을 받을 수 있습니다."])],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "sibling_relation",
        "e698c32ded",
        "고객 간 사적 분쟁에 회사가 개입하는 원칙과 예외는 무엇이야?",
        [
            req("general_rule", "고객 간 사적 분쟁", "company_intervention_rule", "text", ["개입하지 않는 것을 원칙"], ["사적인 분쟁에 개입하지 않는 것을 원칙"]),
            req("exception", "고객 간 사적 분쟁", "intervention_exception", "text", ["불특정 다수의 고객에게 피해를 주는 경우"], ["불특정 다수의 고객에게 피해"]),
        ],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "multi_requirement",
        "e698c32ded",
        "운영정책에서 고객이 ID를 보호하기 위해 해야 하는 두 가지 의무는 뭐야?",
        [
            req("security_service", "고객 ID 보호", "security_service_obligation", "text", ["회사가 제공하는 보안서비스 이용"], ["고객은 자신의 ID를 보호하기 위해 회사에서 제공하는 보안서비스(OTP 등)에 가입하는 등의 노력을 해야 합니다."]),
            req("credential_secrecy", "고객 ID 보호", "credential_secrecy_obligation", "text", ["ID와 비밀번호가 타인에게 노출되지 않도록 관리"], ["고객은 ID, 비밀번호 등의 계정정보 및 개인정보가 타인에게 노출되지 않도록 최선의 주의를 기울여야 하며"]),
        ],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "table_attribute",
        "e698c32ded",
        "운영자나 직원을 사칭했을 때 1차와 4차 이용제한 기간은 각각 얼마야?",
        [
            req("first_sanction", "운영자/직원 사칭", "first_sanction", "text", ["100일 게임 이용제한"], ["| 운영자 / 직원을 사칭하는 행위 | 100일 게임 이용제한 | 1년 게임 이용제한 | 3년 게임 이용제한 | 영구 게임 이용제한 |"]),
            req("fourth_sanction", "운영자/직원 사칭", "fourth_sanction", "text", ["영구 게임 이용제한"], ["| 운영자 / 직원을 사칭하는 행위 | 100일 게임 이용제한 | 1년 게임 이용제한 | 3년 게임 이용제한 | 영구 게임 이용제한 |"]),
        ],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "revision_selection",
        "e698c32ded",
        "현재 운영정책이 변경될 때 회사는 고객에게 어떤 방식으로 알려줘?",
        [req("change_notice_method", "던전앤파이터 운영정책 변경", "notice_method", "text", ["공지를 통해 안내"], ["운영정책을 변경할 경우, 회사는 관련 내용을 넥슨 공식 홈페이지(http://www.nexon.com)나 게임 홈페이지(http://df.nexon.com) 공지를 통해 알려드립니다."])],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "unsupported_or_partial",
        "e698c32ded",
        "게임 이용제한에 이의가 있으면 어디로 신청하고, 처리 기한은 정확히 며칠이야?",
        [
            req("appeal_channel", "게임 이용제한 이의신청", "appeal_channel", "text", ["고객센터"], ["이용제한 적용 시 이의신청을 원하실 경우, 고객센터로 문의하여 주시기 바랍니다."]),
            req("processing_days", "게임 이용제한 이의신청", "processing_days", "number", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    case(
        "dnf_account_policy",
        "direct_fact",
        "e698c32ded",
        "운영정책상 이용제한 근거 데이터는 며칠 동안 보유해?",
        [req("retention_days", "이용제한 근거 데이터", "retention_days", "number", [90], ["이용제한 근거에 대한 데이터는 관계 법령에 근거하여 90일간 보유"])],
        parent_overlap_exception_reason="운영정책은 현재 공식 revision이 한 개뿐이므로 parent 재사용을 허용하되 신규 관계와 질문만 사용합니다.",
    ),
    # dnf_seria_shop
    case(
        "dnf_seria_shop",
        "temporal_role",
        "1272cbccdf",
        "프리미엄 코인샵의 트로피컬 바캉스 무기 아바타 상자는 언제 삭제돼?",
        [req("deletion_at", "[프리미엄 코인샵]트로피컬 바캉스 무기 아바타 상자", "deletion_at", "datetime", ["2026-08-27T06:00:00+09:00"], ["| [프리미엄 코인샵]트로피컬 바캉스 무기 아바타 상자 | 2개 | 계정당 5회 | 2026년 8월 27일 06시 |"])],
    ),
    case(
        "dnf_seria_shop",
        "boolean_direction",
        "c5d4dc9396",
        "장비 보호권은 증폭에도 적용돼?",
        [req("applies_to_amplification", "장비 보호권", "applies_to_amplification", "boolean", [False], ["| 장비 보호권 | 9,800 세라 | 교환가능 | NPC 키리의 강화 메뉴나 1회용 강화기를 사용해서 무기를 13강 이상 / 그 외 장비를 11강 이상으로 강화에 시도하는 경우, 강화에 실패하여 장비가 파괴될 때 캐릭터 인벤토리에 있는 장비 보호권 1개가 자동으로 소모되면서 장비를 보호합니다. 파괴로부터 보호된 장비는 강화 수치가 +0이 됩니다. 증폭에는 적용 되지 않습니다. | 무제한 | |"])],
    ),
    case(
        "dnf_seria_shop",
        "sibling_relation",
        "af00175687",
        "일반 상의 아바타와 상의 클론 아바타의 가격은 각각 얼마야?",
        [
            req("top_price", "상의 아바타", "price", "currency", [{"amount": 6500, "unit": "세라"}], ["| 상의 | 6,500 세라 |"]),
            req("clone_top_price", "상의 클론 아바타", "price", "currency", [{"amount": 2600, "unit": "세라"}], ["| 상의 클론 | 2,600 세라 |"]),
        ],
    ),
    case(
        "dnf_seria_shop",
        "multi_requirement",
        "81bb78a045",
        "통큰 패키지 A의 가격, 거래 타입, 사용 기간은 각각 뭐야?",
        [
            req("price", "통큰 패키지 A", "price", "currency", [{"amount": 22600, "unit": "세라"}], ["| 통큰 패키지 A | 22,600 세라 | 계정귀속 | 달인의 계약 30일, 패왕의 계약 30일, 가브리엘의 계약 30일, 해방의 열쇠 10개가 들어 있습니다. 가브리엘의 계약 : 가브리엘의 등장확률과 판매종류 및 개수가 증가합니다.(단, 에픽조각교환 가브리엘은 제외) | 무제한 | |"]),
            req("trade_type", "통큰 패키지 A", "trade_type", "enum", ["계정귀속"], ["| 통큰 패키지 A | 22,600 세라 | 계정귀속 | 달인의 계약 30일, 패왕의 계약 30일, 가브리엘의 계약 30일, 해방의 열쇠 10개가 들어 있습니다. 가브리엘의 계약 : 가브리엘의 등장확률과 판매종류 및 개수가 증가합니다.(단, 에픽조각교환 가브리엘은 제외) | 무제한 | |"]),
            req("duration", "통큰 패키지 A", "duration", "enum", ["무제한"], ["| 통큰 패키지 A | 22,600 세라 | 계정귀속 | 달인의 계약 30일, 패왕의 계약 30일, 가브리엘의 계약 30일, 해방의 열쇠 10개가 들어 있습니다. 가브리엘의 계약 : 가브리엘의 등장확률과 판매종류 및 개수가 증가합니다.(단, 에픽조각교환 가브리엘은 제외) | 무제한 | |"]),
        ],
    ),
    case(
        "dnf_seria_shop",
        "table_attribute",
        "c5d4dc9396",
        "증폭 보호권의 가격과 거래 타입은 뭐야?",
        [
            req("price", "증폭 보호권", "price", "currency", [{"amount": 12900, "unit": "세라"}], ["| 증폭 보호권 | 12,900 세라 | 교환가능 |"]),
            req("trade_type", "증폭 보호권", "trade_type", "enum", ["교환가능"], ["| 증폭 보호권 | 12,900 세라 | 교환가능 |"]),
        ],
    ),
    case(
        "dnf_seria_shop",
        "revision_selection",
        "af00175687",
        "현재 아바타 관련 안내에서 피부 아바타의 골드 코인 가격은 얼마야?",
        [req("gold_coin_price", "피부 아바타", "gold_coin_price", "currency", [{"amount": 10, "unit": "골드 코인"}], ["| 피부 | 10 골드 코인 | 교환불가 |"])],
    ),
    case(
        "dnf_seria_shop",
        "unsupported_or_partial",
        "81bb78a045",
        "하트비트 메가폰 10개의 가격과 계정당 구매 제한을 알려줘.",
        [
            req("price", "하트비트 메가폰 10개", "price", "currency", [{"amount": 5800, "unit": "세라"}], ["| 하트비트 메가폰 10개 | 5,800 세라 | 교환가능 |"]),
            req("purchase_limit", "하트비트 메가폰 10개", "account_purchase_limit", "number", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
    ),
    case(
        "dnf_seria_shop",
        "direct_fact",
        "81bb78a045",
        "무한 올빼미는 어디에서 사용할 수 있어?",
        [req("usable_locations", "무한 올빼미", "usable_locations", "entity_list", ["마을", "던전"], ["마을, 던전에서 사용이 가능합니다."])],
    ),
    # dnf_monthly_item
    case(
        "dnf_monthly_item",
        "temporal_role",
        "ac6eaa98e",
        "7월 이달의 아이템 판매 기간은 언제부터 언제까지야?",
        [req("sale_period", "7월 이달의 아이템", "sale_period", "date_range", ["2026-06-25", "2026-07-30"], ["판매기간: 06.25 ~ 07.30"])],
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
    case(
        "dnf_monthly_item",
        "boolean_direction",
        "ac6eaa98e",
        "7월 이달의 아이템은 다른 계정과 교환할 수 있어?",
        [req("tradeable", "7월 이달의 아이템", "is_tradeable", "boolean", [True], ["거래타입\n교환가능"])],
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
    case(
        "dnf_monthly_item",
        "sibling_relation",
        "ac6eaa98e",
        "7월 이달의 아이템을 사용하면 얻는 두 상자 이름을 알려줘.",
        [
            req(
                "obtained_items",
                "7월 이달의 아이템",
                "obtained_items",
                "entity_list",
                ["[7월]클론 레어 아바타(교환불가) 풀세트 상자", "[7월]찬란한 엠블렘(계정귀속) 풀세트 선택상자"],
                ["[7월]클론 레어 아바타(교환불가) 풀세트 상자", "[7월]찬란한 엠블렘(계정귀속) 풀세트 선택상자"],
            )
        ],
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
    case(
        "dnf_monthly_item",
        "multi_requirement",
        "ac6eaa98e",
        "7월 이달의 아이템의 상점 판매가와 삭제 시각은 각각 얼마와 언제야?",
        [
            req("shop_price", "7월 이달의 아이템", "shop_price", "currency", [{"amount": 40000000, "unit": "골드"}], ["상점판매가\n4,000만 골드"]),
            req("deletion_at", "7월 이달의 아이템", "deletion_at", "datetime", ["2026-08-13T06:00:00+09:00"], ["2026년 08월 13일 06시 일괄삭제"]),
        ],
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
    case(
        "dnf_monthly_item",
        "table_attribute",
        "ac6eaa98e",
        "7월 이달의 아이템의 거래 타입과 상점 판매가는 뭐야?",
        [
            req("trade_type", "7월 이달의 아이템", "trade_type", "enum", ["교환가능"], ["거래타입\n교환가능"]),
            req("shop_price", "7월 이달의 아이템", "shop_price", "currency", [{"amount": 40000000, "unit": "골드"}], ["상점판매가\n4,000만 골드"]),
        ],
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
    case(
        "dnf_monthly_item",
        "revision_selection",
        "6510122be6",
        "6월 이달의 아이템은 언제 일괄 삭제됐어?",
        [req("deletion_at", "6월 이달의 아이템", "deletion_at", "datetime", ["2026-07-09T06:00:00+09:00"], ["2026년 7월 9일 06시 일괄삭제"])],
        time_scope="historical",
        parent_overlap_exception_reason="월별 공식 revision 비교를 위해 과거 6월 parent를 사용하며 질문과 관계는 신규입니다.",
    ),
    case(
        "dnf_monthly_item",
        "unsupported_or_partial",
        "ac6eaa98e",
        "7월 이달의 아이템 상점 판매가와 8월 이달의 아이템 이름을 알려줘.",
        [
            req("july_shop_price", "7월 이달의 아이템", "shop_price", "currency", [{"amount": 40000000, "unit": "골드"}], ["상점판매가\n4,000만 골드"]),
            req("august_item_name", "8월 이달의 아이템", "item_name", "entity", [], [], expected_status="unsupported"),
        ],
        expected_response_mode="partial_answer",
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
    case(
        "dnf_monthly_item",
        "direct_fact",
        "ac6eaa98e",
        "이달의 아이템은 세라샵에서 어떤 방식으로 획득해?",
        [req("acquisition_method", "이달의 아이템", "acquisition_method", "text", ["해방의 열쇠로 봉인된 자물쇠를 열어 확률적으로 획득"], ["세라샵에서 구매한 ‘해방의 열쇠’로 ‘봉인된 자물쇠’를 열어 특정 확률에 따라 이달의 아이템을 획득할 수 있습니다."])],
        parent_overlap_exception_reason="이달의 아이템은 현재 월 revision이 한 개뿐이므로 신규 관계와 질문에 한해 parent 재사용을 허용합니다.",
    ),
]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_sha256_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def find_document(documents: list[dict[str, Any]], source_id: str, suffix: str) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if document["source_id"] == source_id and document["document_id"].endswith(suffix)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one document for {source_id}/{suffix}, got {len(matches)}")
    return matches[0]


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


def build_rows(
    slots: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(SPECS) != 64:
        raise RuntimeError(f"expected 64 specs, got {len(SPECS)}")
    chunks_by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk["parent_document_id"], []).append(chunk)

    rows = []
    for slot, spec in zip(slots, SPECS, strict=True):
        for field in ("source_id", "primary_dimension"):
            if slot[field] != spec[field]:
                raise RuntimeError(
                    f"slot {slot['slot_ordinal']} {field} mismatch: {slot[field]} != {spec[field]}"
                )
        primary_document = find_document(documents, spec["source_id"], spec["document_suffix"])
        requirements = []
        for requirement in spec["requirements"]:
            evidence_units = []
            evidence_document = primary_document
            if requirement["document_suffix"]:
                evidence_document = find_document(
                    documents, spec["source_id"], requirement["document_suffix"]
                )
            for needle in requirement["evidence_needles"]:
                evidence_units.append(
                    find_evidence_unit(chunks_by_document, evidence_document, needle)
                )
            requirements.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "subject": requirement["subject"],
                    "relation": requirement["relation"],
                    "value_type": requirement["value_type"],
                    "required_values": requirement["required_values"],
                    "acceptable_evidence_units": evidence_units,
                    "expected_status": requirement["expected_status"],
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
                "packet_schema_version": "typed-evidence-ref-generalization-candidate-v1",
                "candidate_id": stable_id("typed_generalization_candidate", identity),
                "question_text": spec["question_text"],
                "as_of": spec["as_of"],
                "time_scope": spec["time_scope"],
                "expected_response_mode": spec["expected_response_mode"],
                "requirements": requirements,
                "primary_document_id": primary_document["document_id"],
                "primary_document_title": primary_document["title"],
                "primary_document_url": primary_document["canonical_url"],
                "parent_overlap_exception_reason": spec["parent_overlap_exception_reason"],
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
                "evaluation_role": "codex_authored_candidate_pending_human_review",
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "slot_ordinal",
        "slot_id",
        "source_id",
        "primary_dimension",
        "candidate_id",
        "question_text",
        "as_of",
        "time_scope",
        "expected_response_mode",
        "primary_document_title",
        "primary_document_url",
        "requirements_json",
        "parent_overlap_exception_reason",
        "author_status",
        "review_status",
        "reviewer_id",
        "reviewed_at",
        "review_rationale",
        "execution_allowed",
        "training_allowed",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{column: row.get(column, "") for column in columns},
                    "requirements_json": json.dumps(
                        row["requirements"], ensure_ascii=False, separators=(",", ":")
                    ),
                    "review_status": row["review"]["status"],
                    "reviewer_id": "",
                    "reviewed_at": "",
                    "review_rationale": "",
                    "execution_allowed": "false",
                    "training_allowed": "false",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slots", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--jsonl-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    outputs = (args.jsonl_output, args.csv_output, args.manifest_output)
    for output in outputs:
        if output.exists():
            raise RuntimeError(f"output already exists: {output}")

    rows = build_rows(
        list(read_jsonl(args.slots)),
        list(read_jsonl(args.documents)),
        list(read_jsonl(args.chunks)),
    )
    write_jsonl(args.jsonl_output, rows)
    write_csv(args.csv_output, rows)
    manifest = {
        "builder_version": BUILDER_VERSION,
        "status": "draft_complete_pending_human_review_execution_locked",
        "row_count": len(rows),
        "pending_review_count": sum(row["review"]["status"] == "pending" for row in rows),
        "execution_allowed_rows": sum(row["execution_allowed"] for row in rows),
        "training_allowed_rows": sum(row["training_allowed"] for row in rows),
        "source_counts": {
            source_id: sum(row["source_id"] == source_id for row in rows)
            for source_id in sorted({row["source_id"] for row in rows})
        },
        "dimension_counts": {
            dimension: sum(row["primary_dimension"] == dimension for row in rows)
            for dimension in sorted({row["primary_dimension"] for row in rows})
        },
        "inputs": {
            "slots": {"path": args.slots.as_posix(), "sha256": sha256_path(args.slots)},
            "documents": {
                "path": args.documents.as_posix(),
                "sha256": sha256_path(args.documents),
            },
            "chunks": {"path": args.chunks.as_posix(), "sha256": sha256_path(args.chunks)},
        },
        "outputs": {
            "jsonl": {
                "path": args.jsonl_output.as_posix(),
                "sha256": sha256_path(args.jsonl_output),
            },
            "csv": {
                "path": args.csv_output.as_posix(),
                "sha256": sha256_path(args.csv_output),
            },
        },
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
