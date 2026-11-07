
import pytest

from novel_distill.codex import protocol
from novel_distill.codex.apply import apply_result
from novel_distill.ingest.importer import add_book
from novel_distill.render.obsidian import render_book
from novel_distill.store import jsonl, migrate
from novel_distill.store.rebuild import rebuild_book

TEXT = """第一卷 七玄门风云

第一章 山边小村

韩立七岁，和父母住在山边小村。他从小就向往外面的世界，梦想走出这个巴掌大的村子。

第二章 青牛镇

韩立跟着三叔去了青牛镇，见到墨大夫。墨大夫给了他一只神秘小瓶，说此物不可示人。
"""


@pytest.fixture()
def applied(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(TEXT, encoding="utf-8")
    add_book(src, slug="t", title="测试书", workdir=tmp_path)
    bdir = tmp_path / "t"
    res = protocol.empty_result("t", "b0001", [1, 2])
    res["entities"] = [
        {"etype": "character", "name": "韩立", "importance": 5, "summary": "主角"},
        {"etype": "character", "name": "墨大夫", "importance": 3},
        {"etype": "pill", "name": "抽髓丸", "importance": 3, "summary": "透支寿命的秘药",
         "data": {"effect": "短期拔高功力", "limit": "十年内必死"}},
        {"etype": "material", "name": "神秘绿液", "importance": 4, "summary": "小瓶所产灵液"},
    ]
    res["relations"] = [{"src": "韩立", "dst": "抽髓丸", "rel": "服用", "chapter": 2}]
    res["evidence"] = [{"entity": "墨大夫", "chapter": 2, "quote": "墨大夫给了他一只神秘小瓶", "kind": "情节"}]
    rep = apply_result(bdir, "b0001", result=res)
    assert rep["applied"]
    return bdir


def test_pill_renders_into_own_folder(applied, tmp_path):
    vault = tmp_path / "vault"
    out = render_book(applied, vault=vault, subdir="修仙蒸馏")
    book = vault / "修仙蒸馏" / "测试书"
    card = book / "12 丹药" / "抽髓丸.md"
    assert card.exists()
    text = card.read_text(encoding="utf-8")
    assert 'type: "pill"' in text
    assert "短期拔高功力" in text and "十年内必死" in text
    # 丹药不在天才地宝目录
    assert not (book / "07 天才地宝" / "抽髓丸.md").exists()
    assert (book / "07 天才地宝" / "神秘绿液.md").exists()
    overview = (book / "00 总览" / "总览.md").read_text(encoding="utf-8")
    assert "12 丹药/抽髓丸" in overview
    assert out["files"] >= 1


def test_retype_moves_entity_and_keeps_counts(applied, tmp_path):
    before = rebuild_book(applied)
    res = migrate.retype(applied, "神秘绿液", "pill")
    assert res["changed"] and res["old_etype"] == "material" and res["new_etype"] == "pill"
    assert res["new_id"].startswith("pill_")
    rows = jsonl.read_jsonl(jsonl.path_for(applied, "entities"))
    rec = next(r for r in rows if r["name"] == "神秘绿液")
    assert rec["etype"] == "pill" and rec["id"] == res["new_id"]
    after = rebuild_book(applied)
    assert after["entities"] == before["entities"]
    assert after["relations"] == before["relations"]
    assert after["evidence"] == before["evidence"]


def test_retype_dry_run_and_unknown_type(applied):
    dry = migrate.retype(applied, "神秘绿液", "pill", dry_run=True)
    assert dry["changed"] and dry["dry_run"]
    rows = jsonl.read_jsonl(jsonl.path_for(applied, "entities"))
    assert next(r for r in rows if r["name"] == "神秘绿液")["etype"] == "material"
    with pytest.raises(ValueError):
        migrate.retype(applied, "神秘绿液", "nope")


def test_retype_idempotent(applied):
    first = migrate.retype(applied, "抽髓丸", "pill")
    second = migrate.retype(applied, "抽髓丸", "pill")
    assert first["changed"] is False
    assert second["changed"] is False
