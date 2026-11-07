import json

import pytest

from novel_distill.codex import protocol
from novel_distill.codex.apply import apply_result
from novel_distill.ingest.importer import add_book
from novel_distill.pack.continue_pack import build as build_continuation
from novel_distill.render.voice import build as build_voice
from novel_distill.store import db, inspect, lint

TEXT = """第一卷 七玄门风云

第一章 山边小村

韩立七岁，和父母住在山边小村。他从小就向往外面的世界，梦想走出这个巴掌大的村子。母亲替他缝了一只兽皮袋，让他贴身收好。

第二章 青牛镇

韩立跟着三叔去了青牛镇，见到墨大夫。墨大夫给了他一只神秘小瓶，说此物不可示人。韩立把瓶子藏进兽皮袋，装作若无其事的样子。

第三章 入门

七玄门招收内门弟子。韩立在山路上遇到厉飞雨，两人结伴同行，约定互相照应。厉飞雨说，山上的规矩，比刀还快。
"""


@pytest.fixture()
def applied(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(TEXT, encoding="utf-8")
    add_book(src, slug="t", title="测试书", workdir=tmp_path)
    bdir = tmp_path / "t"
    res = protocol.empty_result("t", "b0001", [1, 2, 3])
    res["entities"] = [
        {
            "etype": "character",
            "name": "韩立",
            "aliases": ["二愣子"],
            "importance": 5,
            "summary": "主角",
            "data": {
                "personality": "谨慎、早熟",
                "voice": "话少，答得留余地",
                "dialogue": ["第1章：他从小就向往外面的世界。"],
                "motivation": "出人头地",
            },
        },
        {
            "etype": "character",
            "name": "墨大夫",
            "importance": 4,
            "summary": "授业者",
            "data": {"personality": "阴沉"},
        },
    ]
    res["relations"] = [{"src": "韩立", "dst": "墨大夫", "rel": "授业", "chapter": 2}]
    res["evidence"] = [
        {"entity": "韩立", "chapter": 1, "quote": "他从小就向往外面的世界", "kind": "性格"},
        {"entity": "墨大夫", "chapter": 2, "quote": "墨大夫给了他一只神秘小瓶", "kind": "情节"},
        {"entity": "韩立", "chapter": 3, "quote": "两人结伴同行，约定互相照应", "kind": "关系"},
    ]
    res["foreshadowings"] = [{"title": "神秘小瓶的来历", "status": "open", "planted_chapter": 2}]
    res["events"] = [{"chapter": 3, "title": "七玄门入门", "participants": ["韩立", "厉飞雨"]}]
    res["summaries"] = [
        {"scope": "chapter", "ref": 1, "text": "韩立出身山边小村，向往外面的世界。"},
        {"scope": "chapter", "ref": 2, "text": "墨大夫赠予神秘小瓶。"},
        {"scope": "chapter", "ref": 3, "text": "韩立与厉飞雨结伴上山。"},
    ]
    (bdir / "results").mkdir(exist_ok=True)
    (bdir / "results" / "b0001.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    apply_result(bdir, "b0001")
    return bdir


def test_voice_cards(applied, tmp_path):
    out = build_voice(applied, out=tmp_path / "voice.md")
    text = (tmp_path / "voice.md").read_text(encoding="utf-8")
    assert out["characters"] == 2
    assert "## 韩立（重要度 5/5）" in text
    assert "话少，答得留余地" in text
    assert "第1章：" in text
    assert "墨大夫（授业）" in text


def test_volume_and_chapter_query(applied):
    conn = db.connect(applied / "book.db")
    try:
        vol = inspect.volume(conn, "t", 1)
        assert vol["lo"] == 1 and vol["hi"] == 3
        assert vol["summarized"] == 3
        assert any(e["name"] == "韩立" for e in vol["entities"])
        ch = inspect.chapter(conn, "t", 3)
        assert ch["summary"].startswith("韩立与厉飞雨")
        assert {e["name"] for e in ch["entities"]} == {"韩立"}
        assert ch["events"][0]["title"] == "七玄门入门"
        assert inspect.volume(conn, "t", 99) is None
        assert inspect.chapter(conn, "t", 99) is None
    finally:
        conn.close()


def test_lint_flags_gaps(applied, tmp_path):
    rep = lint.lint(applied, vault=tmp_path / "vault")
    kinds = rep["counts"]
    assert kinds.get("no_dialogue") == 1  # 墨大夫重要度 4 但没对白
    assert kinds.get("thin_entity") == 1  # 墨大夫只有 1 条证据
    assert rep["ok"] is True
    md = lint.markdown(rep)
    assert "设定库自检" in md and "no_dialogue" in md


def test_continuation_has_style_paragraphs(applied, tmp_path, monkeypatch):
    monkeypatch.setattr("novel_distill.pack.continue_pack.resolve_vault", lambda *a, **k: tmp_path / "vault")
    out = build_continuation(applied, upto=3, recent=2)
    text = (tmp_path / "vault" / "修仙蒸馏" / "测试书" / "11 续写" / "续写上下文.md").read_text(encoding="utf-8")
    assert out["chars"] > 0
    assert "文风样本" in text
    assert "他从小就向往外面的世界" in text
