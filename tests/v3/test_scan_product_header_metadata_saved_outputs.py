from src.v3.scan_product_header_metadata_saved_outputs import _header_kind


def test_header_kind_matches_only_exact_header_coordinate() -> None:
    text = "\n".join(
        (
            "### 공지사항",
            "일반",
            "제목",
            "2025.08.12 14:00",
            "37,477",
            "안녕하세요.",
        )
    )
    chunk_id = "chunk-1"
    chunks = {chunk_id: {"display_text": text}}
    start = text.index("2025.08.12 14:00")
    assert (
        _header_kind(
            {
                "chunk_id": chunk_id,
                "start_char": start,
                "end_char": start + 16,
            },
            chunks_by_id=chunks,
            question="점검은 몇 시에 시작해?",
        )
        == "published_timestamp"
    )
    assert (
        _header_kind(
            {"chunk_id": chunk_id, "start_char": 0, "end_char": len(text)},
            chunks_by_id=chunks,
            question="점검은 몇 시에 시작해?",
        )
        is None
    )


def test_header_kind_ignores_timestamp_kept_for_publication_question() -> None:
    text = "\n".join(
        (
            "### 공지사항",
            "일반",
            "제목",
            "2025.08.12 14:00",
            "37,477",
            "안녕하세요.",
        )
    )
    chunk_id = "chunk-1"
    chunks = {chunk_id: {"display_text": text}}
    start = text.index("2025.08.12 14:00")
    assert (
        _header_kind(
            {
                "chunk_id": chunk_id,
                "start_char": start,
                "end_char": start + 16,
            },
            chunks_by_id=chunks,
            question="이 공지는 언제 게시됐어?",
        )
        is None
    )
