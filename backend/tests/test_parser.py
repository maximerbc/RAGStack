from app.services.parser import DocumentParser


def test_markdown_parser_preserves_heading_hierarchy(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text(
        "# Product\n\nOverview text.\n\n## Revenue\n\nRevenue grew 27%.", encoding="utf-8"
    )
    title, blocks = DocumentParser().parse(path)
    assert title == "guide"
    assert blocks[-1].headings == ["Product", "Revenue"]


def test_html_parser_removes_scripts_and_preserves_tables(tmp_path):
    path = tmp_path / "report.html"
    path.write_text(
        "<title>Report</title><h1>Data</h1><script>bad()</script><p>Useful</p><table><tr><td>27%</td></tr></table>",
        encoding="utf-8",
    )
    title, blocks = DocumentParser().parse(path)
    assert title == "Report"
    assert all("bad" not in block.text for block in blocks)
    assert any(block.content_type == "table" for block in blocks)
