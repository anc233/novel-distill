from novel_distill.ingest import keywords
from novel_distill.ingest.importer import add_book
from novel_distill.store import jsonl

TEXT = """第一章 山边小村

韩立说道：“我不去。”张铁笑道：“你怕什么。”韩立摇头，还是不去。张铁又说了一遍，韩立才点头。

第二章 青牛镇

韩立跟着三叔去了青牛镇。张铁说道：“这里比村里热闹。”韩立说道：“人多，眼杂。”张铁便不再开口。
"""


def test_collect_names_and_new_ones(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(TEXT, encoding="utf-8")
    add_book(src, slug="t", title="测试书", workdir=tmp_path)
    bdir = tmp_path / "t"
    jsonl.upsert_many(bdir, "entities", [{"id": "char_hanli", "etype": "character", "name": "韩立"}])

    rep = keywords.collect(bdir, start=1, count=2, top=20)
    names = {r["name"]: r for r in rep["names"]}
    assert "韩立" in names, rep["names"]
    assert names["韩立"]["known"] is True
    assert "张铁" in names, rep["names"]
    assert names["张铁"]["known"] is False
    assert "张铁" in [r["name"] for r in rep["new_names"]]
    assert rep["chapters"] == [1, 2]
    assert rep["engine"] in ("jieba", "fallback")

    md = keywords.markdown(rep)
    assert "新人名候选" in md and "张铁" in md
    assert "韩立" in md
