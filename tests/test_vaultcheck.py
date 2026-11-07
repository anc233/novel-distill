"""vault 双链自检（依赖可选包 obsidiantools）。"""

import pytest

pytest.importorskip("obsidiantools.api")

from novel_distill.store.vaultcheck import check_vault


def test_broken_links_and_orphans(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "甲.md").write_text("# 甲\n\n见 [[乙]] 与 [[缺页]]。\n", encoding="utf-8")
    (vault / "乙.md").write_text("# 乙\n\n回到 [[甲]]。\n", encoding="utf-8")
    (vault / "丙.md").write_text("# 丙\n\n孤岛笔记。\n", encoding="utf-8")

    rep = check_vault(vault)

    assert rep["available"] is True
    assert rep["notes"] == 3
    assert [(b["note"], b["target"]) for b in rep["broken_links"]] == [("甲", "缺页")]
    assert rep["orphan_notes"] == ["丙"]


def test_path_qualified_links_resolve_by_suffix(tmp_path):
    """渲染器写的是 [[修仙蒸馏/书名/01 角色/某某|别名]]，按 Obsidian 的后缀规则应能解析。"""
    vault = tmp_path / "vault"
    (vault / "书" / "角色").mkdir(parents=True)
    (vault / "书" / "角色" / "甲.md").write_text(
        "# 甲\n\n见 [[书/角色/乙|乙]]、[[角色/乙]] 与 [[乙.md]]，还有 [[书/角色/缺页]]。\n", encoding="utf-8"
    )
    (vault / "书" / "角色" / "乙.md").write_text("# 乙\n\n回到 [[甲]]。\n", encoding="utf-8")

    rep = check_vault(vault)

    assert rep["notes"] == 2
    assert [(b["note"], b["target"]) for b in rep["broken_links"]] == [("甲", "书/角色/缺页")]
    assert rep["orphan_notes"] == []


def test_markdown_links_are_checked_too(tmp_path):
    """--plain-links 输出标准 Markdown 链接，也要能算断链/孤立，不能全判成孤岛。"""
    vault = tmp_path / "vault"
    (vault / "书" / "01 角色").mkdir(parents=True)
    (vault / "书" / "01 角色" / "甲.md").write_text(
        "# 甲\n\n[乙](乙.md)、[丙](../02 怪物/丙.md) 与 [缺](../02 怪物/缺.md)\n", encoding="utf-8"
    )
    (vault / "书" / "01 角色" / "乙.md").write_text("# 乙\n\n[甲](%E7%94%B2.md)\n", encoding="utf-8")
    (vault / "书" / "02 怪物").mkdir(parents=True)
    (vault / "书" / "02 怪物" / "丙.md").write_text("# 丙\n\n孤岛。\n", encoding="utf-8")

    rep = check_vault(vault)

    assert rep["links"] >= 2
    assert [(b["note"], b["target"]) for b in rep["broken_links"]] == [("书/01 角色/甲", "../02 怪物/缺.md")]
    assert rep["orphan_notes"] == []


def test_missing_dir_is_reported_not_raised(tmp_path):
    rep = check_vault(tmp_path / "nope")
    assert rep["available"] is False
    assert "不存在" in rep["reason"]
