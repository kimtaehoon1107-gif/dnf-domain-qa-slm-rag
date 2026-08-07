from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


STRUCTURED_FAMILIES = frozenset(
    {
        "boolean_state",
        "item_content",
        "percentage_effect",
        "price_currency",
        "quantity_limit",
        "temporal",
        "trade_status",
    }
)


@dataclass(frozen=True)
class RelationContract:
    family: str
    parent_relation: str
    allowed_value_types: frozenset[str]
    validation_mode: str
    canonical_value_type: str | None = None


def _contract(
    family: str,
    parent_relation: str,
    *value_types: str,
    canonical_value_type: str | None = None,
) -> RelationContract:
    return RelationContract(
        family=family,
        parent_relation=parent_relation,
        allowed_value_types=frozenset(value_types),
        validation_mode=(
            "typed_family" if family in STRUCTURED_FAMILIES else "audit_only"
        ),
        canonical_value_type=canonical_value_type,
    )


RELATION_CONTRACTS = {
    "account_input_limit": _contract(
        "quantity_limit", "per_account_limit", "number"
    ),
    "account_purchase_limit": _contract(
        "quantity_limit", "per_account_limit", "number"
    ),
    "account_receive_limit": _contract(
        "quantity_limit", "per_account_limit", "number"
    ),
    "acquisition_method": _contract(
        "channel_location_method", "method", "text"
    ),
    "additional_fee": _contract(
        "percentage_effect", "fee_rate", "percentage"
    ),
    "appeal_channel": _contract(
        "channel_location_method", "channel", "text"
    ),
    "applies_to_amplification": _contract(
        "boolean_state", "applicability", "boolean"
    ),
    "applies_to_duel_arena": _contract(
        "boolean_state", "applicability", "boolean"
    ),
    "attack_amplification": _contract(
        "percentage_effect", "effect_rate", "percentage"
    ),
    "base_fee": _contract(
        "percentage_effect", "fee_rate", "percentage"
    ),
    "broadcast_at": _contract(
        "temporal", "point_in_time", "datetime"
    ),
    "broadcast_channels": _contract(
        "channel_location_method", "channel", "entity_list"
    ),
    "buff_amplification": _contract(
        "percentage_effect", "effect_rate", "percentage"
    ),
    "can_reissue": _contract(
        "boolean_state", "availability", "boolean"
    ),
    "can_request_cross_channel": _contract(
        "channel_location_method", "availability", "boolean"
    ),
    "change": _contract(
        "effect_change", "change_description", "enum"
    ),
    "changes_to_untradeable": _contract(
        "trade_status", "trade_status", "boolean"
    ),
    "company_intervention_rule": _contract(
        "policy_rule", "policy_rule", "text"
    ),
    "control_keys": _contract(
        "domain_property", "ui_property", "text"
    ),
    "credential_secrecy_obligation": _contract(
        "policy_rule", "security_obligation", "text"
    ),
    "credit_amount": _contract(
        "price_currency", "credit", "number", "currency"
    ),
    "credited_after": _contract(
        "temporal", "duration", "number"
    ),
    "daily_reset_time": _contract(
        "temporal",
        "recurring_reset_at",
        "enum",
        "time",
        canonical_value_type="time",
    ),
    "deletion_at": _contract(
        "temporal", "point_in_time", "datetime"
    ),
    "deletion_location": _contract(
        "channel_location_method", "location", "entity_list"
    ),
    "displayed_information": _contract(
        "effect_change", "display_description", "text"
    ),
    "drawing_goods_quantity": _contract(
        "quantity_limit", "count", "number"
    ),
    "duration": _contract(
        "temporal", "duration", "enum", "number"
    ),
    "effective_at": _contract(
        "temporal", "point_in_time", "date", "datetime"
    ),
    "event_period": _contract(
        "temporal", "time_period", "date_range"
    ),
    "first_sanction": _contract(
        "policy_rule", "sanction", "text"
    ),
    "fixed_at": _contract(
        "temporal", "point_in_time", "datetime"
    ),
    "fourth_sanction": _contract(
        "policy_rule", "sanction", "text"
    ),
    "gold_coin_price": _contract(
        "price_currency", "price", "currency"
    ),
    "improvement": _contract(
        "effect_change", "change_description", "text"
    ),
    "intervention_exception": _contract(
        "policy_rule", "policy_rule", "text"
    ),
    "investigation_status": _contract(
        "domain_property", "state", "enum"
    ),
    "is_fixed": _contract(
        "boolean_state", "state", "boolean"
    ),
    "is_normally_rendered": _contract(
        "boolean_state", "state", "boolean"
    ),
    "is_tradeable": _contract(
        "trade_status", "trade_status", "boolean"
    ),
    "item_name": _contract(
        "item_content", "item_content", "entity"
    ),
    "location": _contract(
        "channel_location_method", "location", "text"
    ),
    "lookup_location": _contract(
        "channel_location_method", "location", "text"
    ),
    "maintenance_time": _contract(
        "temporal",
        "time_period",
        "date_range",
        "time_range",
        canonical_value_type="time_range",
    ),
    "maximum_saved_presets": _contract(
        "quantity_limit", "count", "number"
    ),
    "may_spread_without_reporting": _contract(
        "boolean_state", "permission", "boolean"
    ),
    "notice_method": _contract(
        "channel_location_method", "channel", "text"
    ),
    "obtained_items": _contract(
        "item_content", "item_content", "entity_list"
    ),
    "part_count": _contract(
        "quantity_limit", "count", "number"
    ),
    "payment_impact": _contract(
        "effect_change", "change_description", "text"
    ),
    "price": _contract(
        "price_currency", "price", "currency", "price"
    ),
    "processing_days": _contract(
        "temporal",
        "duration",
        "number",
        "duration_range",
        canonical_value_type="duration_range",
    ),
    "purchase_limit": _contract(
        "quantity_limit", "limit", "number"
    ),
    "recommended_action": _contract(
        "channel_location_method", "action", "enum"
    ),
    "redeem_location": _contract(
        "channel_location_method", "location", "text"
    ),
    "reduction_percentage": _contract(
        "percentage_effect", "effect_rate", "percentage"
    ),
    "registration_location": _contract(
        "channel_location_method", "location", "enum"
    ),
    "remaining_stock": _contract(
        "quantity_limit", "count", "number"
    ),
    "required_character_level": _contract(
        "quantity_limit", "requirement", "number"
    ),
    "required_colorless_cube_fragments": _contract(
        "quantity_limit", "requirement", "number"
    ),
    "retention_days": _contract(
        "temporal", "duration", "number"
    ),
    "revision_cutoff": _contract(
        "temporal", "point_in_time", "date"
    ),
    "sale_period": _contract(
        "temporal", "time_period", "date_range"
    ),
    "searchable_and_equippable_equipment_level": _contract(
        "quantity_limit",
        "eligibility",
        "entity_list",
    ),
    "security_service_obligation": _contract(
        "policy_rule", "security_obligation", "text"
    ),
    "shop_price": _contract(
        "price_currency", "price", "currency", "price"
    ),
    "slot_count": _contract(
        "quantity_limit", "count", "number"
    ),
    "stopped_at": _contract(
        "temporal", "point_in_time", "date", "datetime"
    ),
    "trade_type": _contract(
        "trade_status", "trade_status", "enum"
    ),
    "usable_after_phone_suspension": _contract(
        "boolean_state", "availability", "boolean"
    ),
    "usable_locations": _contract(
        "channel_location_method", "location", "entity_list"
    ),
    "weekly_reset_at": _contract(
        "temporal", "recurring_reset_at", "enum", "time"
    ),
    "withdrawal_period_days": _contract(
        "temporal", "duration", "number"
    ),
}

SHADOW_SEMANTIC_PARENT_RELATIONS = frozenset(
    {
        "applicability",
        "availability",
        "count",
        "duration",
        "effect_rate",
        "eligibility",
        "limit",
        "per_account_limit",
        "point_in_time",
        "price",
        "recurring_reset_at",
        "time_period",
        "trade_status",
    }
)

RELATION_SEMANTIC_ANCHOR_GROUPS = {
    "account_input_limit": (("계정당",), ("입력",)),
    "account_purchase_limit": (("계정당",), ("구매",)),
    "account_receive_limit": (("계정당",), ("보상", "수령", "받")),
    "additional_fee": (("추가",), ("수수료",)),
    "applies_to_amplification": (("증폭",), ("적용",)),
    "applies_to_duel_arena": (("결투장",), ("적용",)),
    "attack_amplification": (("공격력",), ("증폭",)),
    "base_fee": (("수수료",),),
    "broadcast_at": (("방송",),),
    "buff_amplification": (("버프력",), ("증폭",)),
    "can_reissue": (("재발급",), ("가능",)),
    "can_request_cross_channel": (("다른채널", "타채널"), ("신청",)),
    "changes_to_untradeable": (("교환불가",), ("변경",)),
    "credited_after": (("적립",), ("이후", "후")),
    "daily_reset_time": (("매일", "일일"), ("갱신", "기준", "초기화")),
    "deletion_at": (("삭제",),),
    "drawing_goods_quantity": (("추첨", "당첨"),),
    "duration": (("사용기간", "기간", "무제한"),),
    "effective_at": (("적용", "시행", "업데이트"),),
    "event_period": (("이벤트",),),
    "fixed_at": (("수정",),),
    "gold_coin_price": (("골드코인",),),
    "is_tradeable": (("교환", "거래"),),
    "maintenance_time": (("점검",),),
    "maximum_saved_presets": (("프리셋",), ("최대",)),
    "part_count": (("부위",),),
    "price": (("가격", "판매가", "세라", "골드", "잔영"),),
    "processing_days": (("처리", "소요"), ("일", "기간")),
    "purchase_limit": (("구매",), ("제한", "회")),
    "reduction_percentage": (("감소",),),
    "remaining_stock": (("재고",), ("남은", "잔여")),
    "retention_days": (("보유", "보관"), ("일", "기간")),
    "revision_cutoff": (("기준",), ("업데이트", "개정")),
    "sale_period": (("판매",),),
    "searchable_and_equippable_equipment_level": (
        ("검색",),
        ("착용",),
    ),
    "shop_price": (("상점판매가", "판매가"),),
    "slot_count": (("칸",),),
    "stopped_at": (("중단",),),
    "trade_type": (
        ("거래타입", "거래유형", "교환가능", "교환불가", "계정귀속"),
    ),
    "usable_after_phone_suspension": (
        ("정지",),
        ("otp",),
        ("이용", "사용"),
    ),
    "weekly_reset_at": (("1주", "주간", "매주"), ("기준", "갱신")),
    "withdrawal_period_days": (("청약철회",), ("일", "기간")),
}


def compact_relation(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").casefold())


def relation_contract(
    relation_or_requirement: str | dict[str, Any],
) -> RelationContract | None:
    relation = (
        relation_or_requirement.get("relation")
        if isinstance(relation_or_requirement, dict)
        else relation_or_requirement
    )
    return RELATION_CONTRACTS.get(str(relation or "").strip())


def relation_families_for_value_type(value_type: str) -> tuple[str, ...]:
    """Return reviewed families that currently allow one typed value shape."""

    normalized = str(value_type or "").strip()
    return tuple(
        sorted(
            {
                contract.family
                for contract in RELATION_CONTRACTS.values()
                if normalized in contract.allowed_value_types
            }
        )
    )


def canonical_value_type(
    relation_or_requirement: str | dict[str, Any],
) -> str | None:
    contract = relation_contract(relation_or_requirement)
    return contract.canonical_value_type if contract is not None else None


def family_type_validation_state(
    requirement: dict[str, Any],
) -> str:
    contract = relation_contract(requirement)
    if contract is None:
        return "unregistered"
    if contract.validation_mode == "audit_only":
        return "audit_only"
    value_type = str(requirement.get("value_type") or "")
    if value_type not in contract.allowed_value_types:
        return "type_mismatch"
    return "typed_family_valid"


def semantic_anchor_groups(
    relation_or_requirement: str | dict[str, Any],
) -> tuple[tuple[str, ...], ...]:
    relation = (
        relation_or_requirement.get("relation")
        if isinstance(relation_or_requirement, dict)
        else relation_or_requirement
    )
    return RELATION_SEMANTIC_ANCHOR_GROUPS.get(
        str(relation or "").strip(),
        (),
    )
