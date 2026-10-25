from views import _format_report_page_for_embed


def test_format_report_page_keeps_code_block_with_urls():
    content = "Mission: Dawn\nReference: https://example.com/intel"
    rendered = _format_report_page_for_embed(content)

    assert rendered.startswith("```txt\n")
    assert rendered.endswith("\n```")
    assert "https://example.com/intel" in rendered


def test_format_report_page_neutralizes_nested_code_fence():
    content = "Header\n```danger```"
    rendered = _format_report_page_for_embed(content)

    assert "``\u200b`danger``\u200b`" in rendered


def test_format_report_page_truncates_to_embed_limit():
    rendered = _format_report_page_for_embed("A" * 2000)

    assert len(rendered) == 1024
    assert rendered.endswith("...")
