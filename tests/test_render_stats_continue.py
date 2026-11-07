import json

import pytest

from novel_distill.codex import protocol
from novel_distill.codex.apply import apply_result
from novel_distill.ingest.importer import add_book
from novel_distill.pack.continue_pack import build as build_continuation
from novel_distill.render.obsidian import render_book
from novel_distill.stats.report import collect, markdown

TEXT = """第一卷 七玄门风云

第一章 山边小村

韩立七岁，和父母住在山边小村。他从小就向往外面的世界，梦想走出这个巴掌大的村子。

第二章 青牛镇

韩立跟着三叔去了青牛镇，见到墨大夫。墨大夫给了他一只神秘小瓶，说此物不可示人。

第三章 入门

七玄门招收内门弟子。韩立在山路上遇到厉飞雨，两人结伴同行，约定互相照应。
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
            "data": {"personality": "谨慎、早熟", "voice": "话少", "motivation": "出人头地"},
        },
        {"etype": "character", "name": "墨大夫", "importance": 3},
    ]
    res["relations"] = [{"src": "韩立", "dst": "墨大夫", "rel": "授业", "chapter": 2}]
    res["evidence"] = [
        {"entity": "韩立", "chapter": 1, "quote": "他从小就向往外面的世界", "kind": "性格"},
        {"entity": "墨大夫", "chapter": 2, "quote": "墨大夫给了他一只神秘小瓶", "kind": "情节"},
    ]
    res["foreshadowings"] = [{"title": "神秘小瓶的来历", "status": "open", "planted_chapter": 2}]
    res["events"] = [{"chapter": 3, "title": "七玄门入门", "participants": ["韩立", "厉飞雨"]}]
    res["summaries"] = [
        {"scope": "chapter", "ref": 1, "text": "韩立出身山边小村，向往外面的世界。"},
        {"scope": "chapter", "ref": 2, "text": "墨大夫赠予神秘小瓶。"},
        {"scope": "chapter", "ref": 3, "text": "韩立与厉飞雨结伴上山。"},
    ]
    import json as _json

    (bdir / "results").mkdir(exist_ok=True)
    (bdir / "results" / "b0001.json").write_text(_json.dumps(res, ensure_ascii=False), encoding="utf-8")
    apply_result(bdir, "b0001")
    return bdir


def test_render_creates_notes_and_links(applied, tmp_path):
    vault = tmp_path / "vault"
    out = render_book(applied, vault=vault)
    root = vault / "修仙蒸馏" / "测试书"
    assert (root / "01 角色" / "韩立.md").exists()
    assert (root / "00 总览" / "总览.md").exists()
    assert (root / "99 统计" / "统计.md").exists()
    note = (root / "01 角色" / "韩立.md").read_text(encoding="utf-8")
    assert 'name: "韩立"' in note
    assert "[[修仙蒸馏/测试书/01 角色/墨大夫|墨大夫]]" in note
    assert "## 原文证据" in note
    assert out["files"] >= 5


def test_render_plain_links_are_standard_markdown(applied, tmp_path):
    """--plain-links：给没有 Obsidian 的编辑器用，链接必须是标准 Markdown 相对路径。"""
    vault = tmp_path / "vault"
    render_book(applied, vault=vault, plain_links=True)
    root = vault / "修仙蒸馏" / "测试书"
    note = (root / "01 角色" / "韩立.md").read_text(encoding="utf-8")
    assert "[[" not in note
    assert "[墨大夫](墨大夫.md)" in note
    overview = (root / "00 总览" / "总览.md").read_text(encoding="utf-8")
    assert "[韩立](../01%20角色/韩立.md)" in overview
    assert "[统计](../99%20统计/统计.md)" in overview
    index = (root / "01 角色" / "角色总表.md").read_text(encoding="utf-8")
    assert "[墨大夫](墨大夫.md)" in index
    # 全库都不该残留双链
    leftovers = [p.name for p in root.rglob("*.md") if "[[" in p.read_text(encoding="utf-8")]
    assert leftovers == []


def test_render_clean_removes_only_manifest_files(applied, tmp_path):

    vault = tmp_path / "vault"
    render_book(applied, vault=vault)
    root = vault / "修仙蒸馏" / "测试书"
    # 上次渲染过、这次已不存在的卡片：在清单里，应被清掉
    stale = root / "01 角色" / "旧角色.md"
    stale.write_text("stale", encoding="utf-8")
    manifest = root / ".rendered.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["generated"].append("01 角色/旧角色.md")
    manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # 用户手写笔记：不在清单里，必须保留
    mine = root / "99 统计" / "我的批注.md"
    mine.write_text("手写", encoding="utf-8")
    render_book(applied, vault=vault, clean=True)
    assert not stale.exists()
    assert mine.exists()


def test_stats_report_coverage(applied):
    rep = collect(applied)
    assert rep["chapters"] == 3
    assert rep["summarized_chapters"] == 3
    assert rep["coverage"] == 1.0
    assert rep["remaining_chapters"] == 0
    assert rep["batches_applied"] == 1
    assert rep["entities"] == 2
    md = markdown(rep)
    assert "抽取进度" in md and "各卷进度" in md


def test_stats_survives_rebuild(applied):
    from novel_distill.store.rebuild import rebuild_book

    rebuild_book(applied)
    rep = collect(applied)
    assert rep["batches_applied"] == 1
    assert rep["entities"] == 2
    assert rep["relations"] == 1


def test_continuation_pack(applied, tmp_path):
    vault = tmp_path / "vault"
    import novel_distill.pack.continue_pack as cp

    old = cp.resolve_vault
    cp.resolve_vault = lambda *a, **k: vault
    try:
        out = build_continuation(applied, style_sample=True)
    finally:
        cp.resolve_vault = old
    assert out["upto"] == 3
    with open(out["path"], encoding="utf-8") as fh:
        text = fh.read()
    assert "当前局势" in text
    assert "主要人物" in text
    assert "神秘小瓶的来历" in text
    assert "文风样本" in text
    assert "已蒸馏：第 1–3 章" in text
    assert out["tokens_est"] > 0
