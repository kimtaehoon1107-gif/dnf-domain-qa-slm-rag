from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl
from src.v3.collect_details import write_immutable
from src.v3.collect_structured_details import DEFAULT_DETAIL_DIR


PARSER_VERSION = "dnf_structured_detail_table_parser_v1.0"
REQUIRED_HEADERS = ("아이템 명", "아이템 설명", "미션")
FIELD_BY_HEADER = {
    "아이템명": "item_name",
    "아이템설명": "item_description",
    "미션": "mission",
}


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split())


def _source_text(tag: Tag) -> str:
    return "\n".join(
        line.strip()
        for line in tag.get_text("\n", strip=True).splitlines()
        if line.strip()
    )


def _css_locator(tag: Tag) -> str:
    parts = []
    current: Tag | None = tag
    while isinstance(current, Tag) and current.name != "[document]":
        index = 1 + sum(
            1
            for sibling in current.previous_siblings
            if isinstance(sibling, Tag) and sibling.name == current.name
        )
        parts.append(f"{current.name}:nth-of-type({index})")
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return ">".join(reversed(parts))


def restore_locator_text(source: str, locator: str) -> str:
    soup = BeautifulSoup(source, "html.parser")
    tag = soup.select_one(locator)
    if tag is None:
        raise RuntimeError(f"HTML locator did not resolve: {locator}")
    return _source_text(tag)


def _direct_rows(table: Tag) -> list[Tag]:
    return [row for row in table.find_all("tr") if row.find_parent("table") is table]


def _direct_cells(row: Tag) -> list[Tag]:
    return row.find_all(["th", "td"], recursive=False)


def _cell_record(cell: Tag, *, origin_row: int) -> dict[str, Any]:
    source_text = _source_text(cell)
    return {
        "source_text": source_text,
        "normalized_text": _normalize(source_text),
        "locator": _css_locator(cell),
        "origin_row": origin_row,
        "rowspan": max(1, int(cell.get("rowspan") or 1)),
        "colspan": max(1, int(cell.get("colspan") or 1)),
    }


def _expanded_rows(table: Tag) -> list[dict[str, Any]]:
    output = []
    active: dict[int, dict[str, Any]] = {}
    remaining: dict[int, int] = {}
    for row_index, row in enumerate(_direct_rows(table)):
        grid = dict(active)
        inherited_columns = set(active)
        column = 0
        new_columns = set()
        for cell in _direct_cells(row):
            while column in grid:
                column += 1
            record = _cell_record(cell, origin_row=row_index)
            for offset in range(record["colspan"]):
                target = column + offset
                grid[target] = record
                if record["rowspan"] > 1:
                    active[target] = record
                    remaining[target] = record["rowspan"] - 1
                    new_columns.add(target)
            column += record["colspan"]
        output.append(
            {
                "row": row,
                "row_index": row_index,
                "grid": [grid[index] for index in range(max(grid, default=-1) + 1)],
                "inherited_columns": inherited_columns,
            }
        )
        for target in list(inherited_columns):
            remaining[target] -= 1
            if remaining[target] <= 0:
                remaining.pop(target, None)
                active.pop(target, None)
        for target in new_columns:
            if remaining.get(target, 0) <= 0:
                remaining.pop(target, None)
                active.pop(target, None)
    return output


def _canonical_header(value: str) -> str:
    compact = re.sub(r"[\s:|]+", "", value)
    if "아이템" in compact and "설명" in compact:
        return "아이템 설명"
    if "아이템" in compact and "명" in compact:
        return "아이템 명"
    if "미션" in compact:
        return "미션"
    return _normalize(value)


def _trade_type(description: str) -> str | None:
    match = re.search(
        r"(거래\s*(?:불가|가능)|교환\s*(?:불가|가능)|계정\s*귀속|캐릭터\s*귀속)",
        description,
    )
    return _normalize(match.group(1)) if match else None


def _deletion_at(description: str) -> str | None:
    iso = re.search(r"(20\d{2}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})\s*삭제", description)
    if iso:
        return iso.group(1)
    korean = re.search(
        r"(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일(?:\s*\([^)]*\))?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?[^.\n]{0,20}삭제",
        description,
    )
    if korean:
        year, month, day, hour, minute = korean.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute or 0):02d}"
    return None


def _event_reward_id(detail_url: str) -> int | None:
    values = parse_qs(urlparse(detail_url).query).get("id") or []
    if not values or not values[0].isdigit():
        return None
    return int(values[0])


def parse_structured_detail_tables(
    source: str,
    *,
    parent_canonical_url: str,
    parent_revision_id: str | None,
    parent_lineage_id: str | None,
    detail_url: str,
    detail_snapshot_sha256: str,
    fetched_at: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(source, "html.parser")
    output = []
    for table_index, table_tag in enumerate(soup.find_all("table")):
        expanded = _expanded_rows(table_tag)
        if not expanded:
            continue
        header_index = next(
            (
                index
                for index, row in enumerate(expanded)
                if row["row"].find("th") is not None
            ),
            0,
        )
        header_cells = expanded[header_index]["grid"]
        headers = [_canonical_header(cell["normalized_text"]) for cell in header_cells]
        header_fields = [FIELD_BY_HEADER.get(re.sub(r"\s+", "", header)) for header in headers]
        required_present = all(field in header_fields for field in FIELD_BY_HEADER.values())
        data_rows = []
        incomplete_reasons = []
        if not required_present:
            incomplete_reasons.append("missing_required_header")
        if len(headers) != len(REQUIRED_HEADERS):
            incomplete_reasons.append("unexpected_header_count")
        for expanded_row in expanded[header_index + 1 :]:
            grid = expanded_row["grid"]
            if not grid or all(not cell["normalized_text"] for cell in grid):
                continue
            row_index = len(data_rows)
            values: dict[str, str] = {}
            source_cells: dict[str, dict[str, Any]] = {}
            cell_locators: dict[str, str] = {}
            origins = []
            for column, field in enumerate(header_fields):
                if field is None or column >= len(grid):
                    continue
                cell = grid[column]
                values[field] = cell["normalized_text"]
                source_cells[field] = {
                    "source_text": cell["source_text"],
                    "normalized_text": cell["normalized_text"],
                    "rowspan": cell["rowspan"],
                    "colspan": cell["colspan"],
                }
                cell_locators[field] = cell["locator"]
                origin_data_row = cell["origin_row"] - header_index - 1
                if origin_data_row < row_index:
                    origins.append(origin_data_row)
            child_marker = expanded_row["row"].find(
                "img",
                src=lambda value: bool(
                    value and "ico_child" in str(value).lower()
                ),
            )
            explicit_parent = None
            if child_marker is not None:
                explicit_parent = next(
                    (
                        parent
                        for parent in reversed(data_rows)
                        if parent["row_relation"] == "independent"
                    ),
                    None,
                )
                if (
                    explicit_parent is not None
                    and "mission" in explicit_parent["source_cells"]
                ):
                    values["mission"] = explicit_parent["mission"]
                    source_cells["mission"] = explicit_parent["source_cells"]["mission"]
                    cell_locators["mission"] = explicit_parent["cell_locators"]["mission"]
            missing_fields = [
                field
                for field in ("item_name", "item_description", "mission")
                if not values.get(field)
            ]
            if missing_fields:
                incomplete_reasons.append("empty_required_cell")
            description = values.get("item_description", "")
            parent_row_index = (
                explicit_parent["row_index"]
                if explicit_parent is not None
                else (min(origins) if origins else None)
            )
            data_rows.append(
                {
                    "row_index": row_index,
                    "item_name": values.get("item_name", ""),
                    "item_description": description,
                    "mission": values.get("mission", ""),
                    "parent_row_index": parent_row_index,
                    "row_relation": (
                        "explicit_child"
                        if explicit_parent is not None
                        else ("rowspan_child" if origins else "independent")
                    ),
                    "trade_type": _trade_type(description),
                    "deletion_at": _deletion_at(description),
                    "detail_snapshot_sha256": detail_snapshot_sha256,
                    "row_locator": _css_locator(expanded_row["row"]),
                    "cell_locators": cell_locators,
                    "source_cells": source_cells,
                }
            )
        if not data_rows:
            incomplete_reasons.append("no_data_rows")
        incomplete_reasons = sorted(set(incomplete_reasons))
        identity = {
            "parent_revision_id": parent_revision_id,
            "detail_url": detail_url,
            "detail_snapshot_sha256": detail_snapshot_sha256,
            "table_index": table_index,
        }
        table_hash = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        output.append(
            {
                "table_schema_version": "dnf_structured_detail_table_v1.0",
                "parser_version": PARSER_VERSION,
                "table_id": f"structured_table_sha256_{table_hash}",
                "parent_canonical_url": parent_canonical_url,
                "parent_revision_id": parent_revision_id,
                "parent_lineage_id": parent_lineage_id,
                "detail_kind": "official_event_reward_popup",
                "detail_url": detail_url,
                "event_reward_id": _event_reward_id(detail_url),
                "detail_snapshot_sha256": detail_snapshot_sha256,
                "fetched_at": fetched_at,
                "table_locator": _css_locator(table_tag),
                "headers": headers,
                "header_locators": [cell["locator"] for cell in header_cells],
                "row_count": len(data_rows),
                "complete": not incomplete_reasons,
                "incomplete_reasons": incomplete_reasons,
                "rows": data_rows,
            }
        )
    return output


def _canonical_json_bytes(value: Any, *, indent: int | None = None) -> bytes:
    if indent is None:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
    return (text + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(row) for row in rows)


def parse_collection(
    collection_rows: list[dict[str, Any]], *, root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    tables = []
    locator_checks = []
    for collection in collection_rows:
        if collection.get("fetch_status") != "success":
            continue
        snapshot_path = root / collection["snapshot_path"]
        source = snapshot_path.read_text(encoding="utf-8")
        parsed = parse_structured_detail_tables(
            source,
            parent_canonical_url=collection["parent_canonical_url"],
            parent_revision_id=collection.get("parent_revision_id"),
            parent_lineage_id=collection.get("parent_lineage_id"),
            detail_url=collection["detail_url"],
            detail_snapshot_sha256=collection["snapshot_sha256"],
            fetched_at=collection["fetched_at"],
        )
        tables.extend(parsed)
        for table in parsed:
            for row in table["rows"]:
                for field, locator in row["cell_locators"].items():
                    locator_checks.append(
                        restore_locator_text(source, locator)
                        == row["source_cells"][field]["source_text"]
                    )
    atomic_rows = []
    for table in tables:
        for row in table["rows"]:
            atomic_rows.append(
                {
                    "atomic_schema_version": "dnf_structured_detail_atomic_row_v1.0",
                    "table_id": table["table_id"],
                    "table_complete": table["complete"],
                    "parent_canonical_url": table["parent_canonical_url"],
                    "parent_revision_id": table["parent_revision_id"],
                    "parent_lineage_id": table["parent_lineage_id"],
                    "detail_url": table["detail_url"],
                    "event_reward_id": table["event_reward_id"],
                    **row,
                }
            )
    audit = {
        "table_count": len(tables),
        "complete_table_count": sum(table["complete"] for table in tables),
        "incomplete_table_count": sum(not table["complete"] for table in tables),
        "atomic_row_count": len(atomic_rows),
        "locator_check_count": len(locator_checks),
        "locator_restore_count": sum(locator_checks),
        "locator_restore_rate": (
            sum(locator_checks) / len(locator_checks) if locator_checks else 0.0
        ),
        "false_complete_count": sum(
            table["complete"] and bool(table["incomplete_reasons"]) for table in tables
        ),
    }
    return tables, atomic_rows, audit


def freeze_parsed_tables(
    tables: list[dict[str, Any]],
    atomic_rows: list[dict[str, Any]],
    *,
    root: Path,
    detail_dir: Path,
    collection_path: Path,
    audit: dict[str, Any],
) -> dict[str, Any]:
    output_dir = detail_dir if detail_dir.is_absolute() else root / detail_dir
    tables.sort(key=lambda row: (row["detail_url"], row["parent_canonical_url"], row["table_id"]))
    atomic_rows.sort(key=lambda row: (row["detail_url"], row["table_id"], row["row_index"]))
    table_bytes = _jsonl_bytes(tables)
    table_sha = hashlib.sha256(table_bytes).hexdigest()
    table_path = output_dir / f"structured_detail_tables_{table_sha}.jsonl"
    write_immutable(table_path, table_bytes)
    atomic_bytes = _jsonl_bytes(atomic_rows)
    atomic_sha = hashlib.sha256(atomic_bytes).hexdigest()
    atomic_path = output_dir / f"structured_detail_atomic_rows_{atomic_sha}.jsonl"
    write_immutable(atomic_path, atomic_bytes)
    manifest = {
        "manifest_schema_version": "dnf_structured_detail_tables_manifest_v1.0",
        "parser_version": PARSER_VERSION,
        "collection_path": collection_path.resolve().relative_to(root.resolve()).as_posix(),
        "collection_sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
        "tables_path": table_path.resolve().relative_to(root.resolve()).as_posix(),
        "tables_sha256": table_sha,
        "atomic_rows_path": atomic_path.resolve().relative_to(root.resolve()).as_posix(),
        "atomic_rows_sha256": atomic_sha,
        "audit": audit,
    }
    manifest_bytes = _canonical_json_bytes(manifest, indent=2)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = output_dir / f"structured_detail_tables_manifest_{manifest_sha}.json"
    write_immutable(manifest_path, manifest_bytes)
    return {
        "tables_path": table_path,
        "atomic_rows_path": atomic_path,
        "manifest_path": manifest_path,
        "audit": audit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse structured detail HTML tables")
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--detail-dir", type=Path, default=DEFAULT_DETAIL_DIR)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    collection_path = args.collection if args.collection.is_absolute() else root / args.collection
    tables, atomic_rows, audit = parse_collection(read_jsonl(collection_path), root=root)
    result = freeze_parsed_tables(
        tables,
        atomic_rows,
        root=root,
        detail_dir=args.detail_dir,
        collection_path=collection_path,
        audit=audit,
    )
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
