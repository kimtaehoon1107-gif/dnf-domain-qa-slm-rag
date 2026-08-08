from __future__ import annotations

import json
from pathlib import Path

from src.v3.collect_structured_details import is_allowed_official_detail_url
from src.v3.discover_structured_details import discover_structured_details
from src.v3.parse_structured_detail_tables import (
    parse_structured_detail_tables,
    restore_locator_text,
)


ROOT = Path(__file__).resolve().parents[2]
PARENT_URL = "https://df.nexon.com/pg/fixture-event"
MICHAELA_URL = "https://df.nexon.com/pg/michaelaevent"


EVENT_HTML = """
<html><body>
  <section class="rewards">
    <h2>이벤트 미션 및 보상</h2>
    <a href="javascript:void(eventRewardPop(808))">보상 설명 자세히 보기</a>
  </section>
</body></html>
"""


POPUP_HTML = """
<html><body>
  <table class="reward">
    <thead><tr><th>아이템 명</th><th>아이템 설명</th><th>미션</th></tr></thead>
    <tbody>
      <tr><td rowspan="2">선택 상자</td><td>거래 불가, 2026-08-20 06:00 삭제</td><td>1주차 클리어</td></tr>
      <tr><td>하위 아이템 설명</td><td>2주차 클리어</td></tr>
    </tbody>
  </table>
</body></html>
"""


CSS_ONLY_HTML = """
<html><head><style>
  .reward-section { background: url('/assets/rewards.png') no-repeat; }
</style></head><body>
  <section class="reward-section"><h2>이벤트 보상</h2></section>
</body></html>
"""


EXTERNAL_HTML = """
<html><body>
  <section><h2>보상</h2>
    <a data-api-url="https://unofficial.example/rewards/42">상세</a>
  </section>
</body></html>
"""


INCOMPLETE_POPUP_HTML = """
<html><body><table>
  <tr><th>아이템 명</th><th>아이템 설명</th></tr>
  <tr><td>상자</td><td>설명</td></tr>
  <tr><td><img src="/ico_child.png">하위 아이템</td><td>하위 설명</td></tr>
</table></body></html>
"""


CHILD_ROW_POPUP_HTML = """
<html><body><table>
  <tr><th>아이템 명</th><th>아이템 설명</th><th>미션</th></tr>
  <tr><td>부모 보상 상자</td><td>상자 설명</td><td>1주차 클리어</td></tr>
  <tr>
    <td><img src="//cdn.df.nexon.com/img/web/item_more/ico_child.png">하위 아이템</td>
    <td colspan="2">하위 아이템 설명</td>
  </tr>
</table></body></html>
"""


def test_discovers_event_reward_popup_without_parent_url_special_case() -> None:
    result = discover_structured_details(EVENT_HTML, PARENT_URL)

    assert len(result["references"]) == 1
    reference = result["references"][0]
    assert reference["detail_kind"] == "official_event_reward_popup"
    assert reference["event_reward_id"] == 808
    assert reference["detail_url"] == (
        "https://df.nexon.com/POP/common/event/event_reward_item.php?id=808"
    )
    assert reference["source_locator"] == "a:nth-of-type(1)@href"


def test_accepts_only_official_detail_hosts_and_blocks_external_data_url() -> None:
    assert is_allowed_official_detail_url(
        "https://df.nexon.com/POP/common/event/event_reward_item.php?id=7"
    )
    assert not is_allowed_official_detail_url("https://unofficial.example/rewards/42")

    result = discover_structured_details(EXTERNAL_HTML, PARENT_URL)
    assert result["references"] == []
    assert len(result["blocked_references"]) == 1
    assert result["blocked_references"][0]["reason"] == "external_domain"


def test_parses_header_order_rows_rowspan_and_restorable_locators() -> None:
    tables = parse_structured_detail_tables(
        POPUP_HTML,
        parent_canonical_url=PARENT_URL,
        parent_revision_id="revision_fixture",
        parent_lineage_id="lineage_fixture",
        detail_url="https://df.nexon.com/POP/common/event/event_reward_item.php?id=7",
        detail_snapshot_sha256="a" * 64,
        fetched_at="2026-08-09T12:00:00+09:00",
    )

    assert len(tables) == 1
    table = tables[0]
    assert table["headers"] == ["아이템 명", "아이템 설명", "미션"]
    assert table["row_count"] == 2
    assert table["complete"] is True
    assert [row["item_name"] for row in table["rows"]] == ["선택 상자", "선택 상자"]
    assert table["rows"][1]["parent_row_index"] == 0
    assert table["rows"][0]["trade_type"] == "거래 불가"
    assert table["rows"][0]["deletion_at"] == "2026-08-20 06:00"

    for row in table["rows"]:
        for field, locator in row["cell_locators"].items():
            restored = restore_locator_text(POPUP_HTML, locator)
            assert restored == row["source_cells"][field]["source_text"]


def test_incomplete_headers_do_not_produce_complete_table() -> None:
    table = parse_structured_detail_tables(
        INCOMPLETE_POPUP_HTML,
        parent_canonical_url=PARENT_URL,
        parent_revision_id="revision_fixture",
        parent_lineage_id="lineage_fixture",
        detail_url="https://df.nexon.com/POP/common/event/event_reward_item.php?id=7",
        detail_snapshot_sha256="b" * 64,
        fetched_at="2026-08-09T12:00:00+09:00",
    )[0]

    assert table["complete"] is False
    assert "missing_required_header" in table["incomplete_reasons"]


def test_colspan_child_row_inherits_parent_mission_without_copying_description() -> None:
    table = parse_structured_detail_tables(
        CHILD_ROW_POPUP_HTML,
        parent_canonical_url=PARENT_URL,
        parent_revision_id="revision_fixture",
        parent_lineage_id="lineage_fixture",
        detail_url="https://df.nexon.com/POP/common/event/event_reward_item.php?id=7",
        detail_snapshot_sha256="c" * 64,
        fetched_at="2026-08-09T12:00:00+09:00",
    )[0]

    child = table["rows"][1]
    assert table["complete"] is True
    assert child["item_description"] == "하위 아이템 설명"
    assert child["mission"] == "1주차 클리어"
    assert child["parent_row_index"] == 0
    assert child["row_relation"] == "explicit_child"
    assert (
        restore_locator_text(CHILD_ROW_POPUP_HTML, child["cell_locators"]["mission"])
        == child["source_cells"]["mission"]["source_text"]
    )


def test_css_only_information_section_is_held_for_visual_review() -> None:
    result = discover_structured_details(CSS_ONLY_HTML, PARENT_URL)

    assert result["references"] == []
    assert len(result["visual_sections"]) == 1
    section = result["visual_sections"][0]
    assert section["status"] == "visual_section_incomplete"
    assert section["ocr_candidate"] is True
    assert section["review_required"] is True
    assert section["default_exposure"] is False


def test_michaela_parent_and_collected_popup_reproduce_23_rows() -> None:
    collection_rows = []
    for path in sorted((ROOT / "data/v3/structured_details").glob("structured_detail_collection_*.jsonl")):
        collection_rows.extend(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
        )
    collected = next(
        row
        for row in collection_rows
        if row["parent_canonical_url"] == MICHAELA_URL
        and row["event_reward_id"] == 808
    )
    snapshot_path = ROOT / collected["snapshot_path"]
    popup_html = snapshot_path.read_text(encoding="utf-8")
    tables = parse_structured_detail_tables(
        popup_html,
        parent_canonical_url=MICHAELA_URL,
        parent_revision_id=collected["parent_revision_id"],
        parent_lineage_id=collected["parent_lineage_id"],
        detail_url=collected["detail_url"],
        detail_snapshot_sha256=collected["snapshot_sha256"],
        fetched_at=collected["fetched_at"],
    )

    complete = [table for table in tables if table["complete"]]
    assert len(complete) == 1
    assert complete[0]["headers"] == ["아이템 명", "아이템 설명", "미션"]
    assert complete[0]["row_count"] == 23
    rows = complete[0]["rows"]
    assert sum("계정/" in row["mission"] for row in rows) == 3
    assert any("1주차 클리어" in row["mission"] for row in rows)
    assert any("2주차 클리어" in row["mission"] for row in rows)
    assert any("TOP 20" in row["mission"] for row in rows)
    assert any(
        row["item_name"] == "[무너진 성자 미카엘라] 치장 선택 상자"
        and "특별 경매" in row["mission"]
        for row in rows
    )
    assert all(
        row["parent_row_index"] is not None
        for row in rows
        if row["row_relation"] == "explicit_child"
    )
    assert all(
        restore_locator_text(popup_html, locator)
        == row["source_cells"][field]["source_text"]
        for row in rows
        for field, locator in row["cell_locators"].items()
    )
