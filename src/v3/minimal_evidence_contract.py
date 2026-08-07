from __future__ import annotations

from typing import Any


NARRATIVE = "narrative"
PRODUCT_RECORD = "product_record"
STRUCTURED_TABLE = "structured_table"

_PRODUCT_RECORD_SOURCE_IDS = frozenset(
    {
        "dnf_monthly_item",
        "dnf_seria_shop",
    }
)
_PRODUCT_RECORD_SOURCE_KINDS = frozenset(
    {
        "monthly_item",
        "shop_product",
    }
)


def source_uses_product_record_contract(
    source_id: str | None,
    source_kind: str | None = None,
) -> bool:
    return (
        source_id in _PRODUCT_RECORD_SOURCE_IDS
        or source_kind in _PRODUCT_RECORD_SOURCE_KINDS
    )


def evidence_contract_for_unit(
    unit: dict[str, Any],
    *,
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ],
) -> str:
    coordinate = (
        str(unit.get("chunk_id") or ""),
        int(unit.get("start_char", -1)),
        int(unit.get("end_char", -1)),
    )
    if coordinate in structured_rows_by_coordinate:
        return STRUCTURED_TABLE
    if source_uses_product_record_contract(
        unit.get("source_id"),
        unit.get("source_kind"),
    ):
        return PRODUCT_RECORD
    return NARRATIVE


def selected_evidence_contract(
    evidence_units: list[dict[str, Any]],
    *,
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ],
) -> dict[str, Any]:
    contracts = sorted(
        {
            evidence_contract_for_unit(
                unit,
                structured_rows_by_coordinate=structured_rows_by_coordinate,
            )
            for unit in evidence_units
        }
    )
    if not contracts:
        branch = "none"
    elif len(contracts) == 1:
        branch = contracts[0]
    elif STRUCTURED_TABLE in contracts:
        branch = STRUCTURED_TABLE
    elif PRODUCT_RECORD in contracts:
        branch = PRODUCT_RECORD
    else:
        branch = NARRATIVE
    return {
        "branch": branch,
        "selected_contracts": contracts,
        "mixed": len(contracts) > 1,
    }


def annotate_prompt_with_evidence_contracts(
    prompt: str,
    *,
    evidence_units_by_ref: dict[str, dict[str, Any]],
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ],
) -> str:
    contract_by_ref = {
        evidence_ref: evidence_contract_for_unit(
            unit,
            structured_rows_by_coordinate=structured_rows_by_coordinate,
        )
        for evidence_ref, unit in evidence_units_by_ref.items()
    }
    lines = []
    for line in prompt.splitlines():
        evidence_ref = line.split("\t", 1)[0]
        contract = contract_by_ref.get(evidence_ref)
        if contract and "\t" in line:
            line = (
                f"{evidence_ref}\tevidence_contract={contract}\t"
                + line.split("\t", 1)[1]
            )
        lines.append(line)
    guidance = (
        "\n근거 계약 규칙:\n"
        "- narrative: 일반 문장 의미를 읽고 요청 relation의 값만 선택하세요.\n"
        "- structured_table: 같은 표 행의 subject·요청 열·값을 함께 확인하세요.\n"
        "- product_record: 같은 상품·월/연도·revision의 값만 선택하세요.\n"
        "- 서로 다른 상품 record의 값을 한 requirement에 합치지 마세요.\n"
    )
    return "\n".join(lines) + guidance
