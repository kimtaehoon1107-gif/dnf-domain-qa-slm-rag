from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from src.v3.harden_detail_parsers import structured_text_hardened


def _structured_text(html: str) -> tuple[str, int]:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id="fixture")
    assert isinstance(node, Tag)
    text, _, table_count, *_ = structured_text_hardened(node)
    return text, table_count


def test_nested_quantity_table_inherits_rowspan_subject_and_expands_colspan() -> None:
    text, table_count = _structured_text(
        """
        <section id="fixture">
          <table>
            <tr><th>아이템 명</th><th colspan="4">획득 가능 난이도</th></tr>
            <tr><td rowspan="2">광휘의 잔재</td><td>-</td><td>-</td><td>O</td><td>O</td></tr>
            <tr><td colspan="4">난이도별 수량
              <table>
                <tr><th>싱글</th><th>매칭</th><th>일반</th><th>하드</th></tr>
                <tr><td>-</td><td>-</td><td>40개</td><td>90개</td></tr>
              </table>
            </td></tr>
            <tr><td rowspan="2">초월의 의지</td><td>O</td><td>O</td><td>O</td><td>O</td></tr>
            <tr><td colspan="4">난이도별 수량
              <table>
                <tr><th>싱글</th><th>매칭</th><th>일반</th><th>하드</th></tr>
                <tr><td colspan="2">100개</td><td colspan="2">200개</td></tr>
              </table>
            </td></tr>
          </table>
        </section>
        """
    )

    rows = text.splitlines()
    assert table_count == 3
    assert (
        "| 광휘의 잔재 | 싱글: - | 매칭: - | 일반: 40개 | 하드: 90개 |"
        in rows
    )
    assert (
        "| 초월의 의지 | 싱글: 100개 | 매칭: 100개 | "
        "일반: 200개 | 하드: 200개 |"
        in rows
    )


def test_simple_table_serialization_stays_unchanged() -> None:
    text, table_count = _structured_text(
        """
        <section id="fixture">
          <table>
            <tr><th>구분</th><th>값</th></tr>
            <tr><td>입장 명성</td><td>108,921</td></tr>
          </table>
        </section>
        """
    )

    assert table_count == 1
    assert text == (
        "[TABLE]\n"
        "| 구분 | 값 |\n"
        "| 입장 명성 | 108,921 |\n"
        "[/TABLE]"
    )
