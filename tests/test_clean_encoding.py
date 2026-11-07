from novel_distill.ingest.clean import clean_text, paragraphs
from novel_distill.ingest.encoding import detect_and_decode, read_text_file


def test_utf8_and_gb18030(tmp_path):
    p = tmp_path / "u.txt"
    p.write_bytes("韩立说：你好。".encode())
    d = read_text_file(p)
    assert d.encoding.lower().startswith("utf-8")
    assert d.ok and "韩立" in d.text

    g = tmp_path / "g.txt"
    g.write_bytes("韩立说：你好。".encode("gb18030"))
    d2 = read_text_file(g)
    assert d2.encoding.lower() == "gb18030"
    assert d2.ok and "韩立" in d2.text


def test_bom_detected():
    d = detect_and_decode("\ufeff韩立".encode("utf-8"))
    assert d.encoding == "utf-8-sig"
    assert d.bom is True
    assert d.text.startswith("韩立")


def test_clean_removes_site_lines_keeps_body():
    text = "正文第一段。\nhttps://example.com/abc\n正文第二段，保留。\n请收藏本站。\n"
    r = clean_text(text)
    assert "正文第一段。" in r.text and "正文第二段，保留。" in r.text
    assert "example.com" not in r.text
    assert r.removed_lines >= 2
    assert paragraphs(r.text) == ["正文第一段。", "正文第二段，保留。"]
