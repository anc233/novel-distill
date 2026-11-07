"""服务层契约：读写分离、只读保护、confirm 要求、doctor 载荷。"""

import pytest

from novel_distill import cli, service

SAMPLE = "第一章 山边小村\n\n韩立七岁，和父母住在山边小村。村里来了个走方郎中厉飞雨，厉飞雨看了看韩立的根骨，说这孩子能修仙。\n\n第二章 青牛镇\n\n两人一起去了青牛镇，见到墨大夫。墨大夫递给他一只神秘小瓶。\n\n第三章 回村\n\n韩立回到山边小村，把神秘小瓶藏好。\n"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    monkeypatch.setenv("NOVEL_DISTILL_WORKSPACE", str(root))
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)  # doctor 会检查 vault 目录存在
    monkeypatch.setenv("NOVEL_DISTILL_VAULT", str(vault))
    monkeypatch.delenv("NOVEL_DISTILL_READONLY", raising=False)
    return root


def _import(ws, tmp_path) -> dict:
    src = tmp_path / "book.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    return service.import_book(src, slug="t", title="测试书")


def test_import_stats_list(ws, tmp_path):
    rep = _import(ws, tmp_path)
    assert rep["slug"] == "t"
    assert rep["chapters"] == 3
    books = service.list_books()
    assert [b["slug"] for b in books] == ["t"]
    stats = service.stats("t")
    assert stats["chapters"] == 3
    assert stats["entities"] == 0


def test_doctor_payload(ws):
    rep = service.doctor()
    assert rep["ok"] is True
    assert {c["name"] for c in rep["checks"]} >= {"Python >= 3.12", "SQLite FTS5", "workspace 可写"}
    assert rep["defaults"]["batch_chapters"] > 0
    assert rep["workspace"].endswith("ws")


def test_doctor_vault_optional_when_unconfigured(ws, tmp_path, monkeypatch):
    """没装 Obsidian、也没配置 vault 时，自检不能因此失败。"""
    monkeypatch.delenv("NOVEL_DISTILL_VAULT", raising=False)
    monkeypatch.setattr(service, "resolve_vault", lambda explicit=None: tmp_path / "missing-vault")
    rep = service.doctor()
    vault = next(c for c in rep["checks"] if c["name"].startswith("Obsidian vault"))
    assert (vault["name"], vault["ok"]) == ("Obsidian vault（可选）", True)
    assert rep["ok"] is True


def test_doctor_vault_explicit_missing_fails(ws, tmp_path):
    """显式指定的 vault 不存在时仍要报错。"""
    rep = service.doctor(vault=tmp_path / "typo-vault")
    vault = next(c for c in rep["checks"] if c["name"].startswith("Obsidian vault"))
    assert vault["ok"] is False
    assert rep["ok"] is False


def test_render_plain_links_via_service(ws, tmp_path):
    from pathlib import Path

    _import(ws, tmp_path)
    vault = tmp_path / "notes"
    service.render("t", vault=str(vault), plain_links=True, confirm=True)
    overview = (Path(vault) / "修仙蒸馏" / "测试书" / "00 总览" / "总览.md").read_text(encoding="utf-8")
    assert "[[" not in overview
    assert "[统计](../99%20统计/统计.md)" in overview


def test_missing_book_has_code(ws):
    with pytest.raises(service.ServiceError) as info:
        service.stats("nope")
    assert info.value.code == "missing"


def test_readonly_blocks_writes(ws, tmp_path, monkeypatch):
    _import(ws, tmp_path)
    monkeypatch.setenv("NOVEL_DISTILL_READONLY", "1")
    with pytest.raises(service.ServiceError) as info:
        service.make_packet("t", start=1, count=2)
    assert info.value.code == "readonly"
    with pytest.raises(service.ServiceError) as info:
        service.render("t", confirm=True)
    assert info.value.code == "readonly"
    # 只读模式下读操作仍然可用
    assert service.stats("t")["chapters"] == 3


def test_apply_requires_confirm(ws, tmp_path):
    _import(ws, tmp_path)
    batch = service.make_packet("t", start=1, count=2)["batch"]
    with pytest.raises(service.ServiceError) as info:
        service.apply("t", batch)
    assert info.value.code == "confirm_required"
    with pytest.raises(service.ServiceError) as info:
        service.render("t")
    assert info.value.code == "confirm_required"


def test_cli_help_lists_new_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "mcp" in out
    assert "gui" in out
