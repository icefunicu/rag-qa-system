from pathlib import Path

from worker.parser import parse_document


def test_parse_txt_splits_by_chapter_heading(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("第01章：开始\n第一段\n\n第02章：继续\n第二段", encoding="utf-8")

    segments = parse_document(file_path, "txt")

    assert len(segments) == 2
    assert segments[0].section_title == "第01章：开始"
    assert segments[0].page_or_loc == "text:1"
    assert segments[1].section_title == "第02章：继续"
    assert "第二段" in segments[1].text


def test_parse_txt_with_gb18030_encoding(tmp_path: Path) -> None:
    file_path = tmp_path / "sample-gbk.txt"
    file_path.write_bytes("第一行\n第二行".encode("gb18030"))

    segments = parse_document(file_path, "txt")

    assert len(segments) == 1
    assert "第一行" in segments[0].text
    assert "第二行" in segments[0].text


def test_parse_txt_without_heading_uses_window_fallback(tmp_path: Path) -> None:
    file_path = tmp_path / "fallback.txt"
    file_path.write_text(("普通段落\n" * 6000), encoding="utf-8")

    segments = parse_document(file_path, "txt")

    assert len(segments) >= 2
    assert all(segment.section_title for segment in segments)
