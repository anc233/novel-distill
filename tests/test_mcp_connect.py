"""MCP 一键接入：只做配置合并与备份，别碰其它配置。"""

import json

import pytest

from novel_distill.gui import mcp_connect as mc

SPEC = {
    "command": "C:\\Python\\python.exe",
    "args": ["-m", "novel_distill", "mcp"],
    "env": {"NOVEL_DISTILL_WORKSPACE": "D:\\数据 目录"},
}


def test_merge_json_keeps_other_servers():
    old = json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"})
    out = json.loads(mc.merge_json(old, SPEC))
    assert out["theme"] == "dark"
    assert out["mcpServers"]["other"] == {"command": "x"}
    assert out["mcpServers"]["novel-distill"] == SPEC


def test_merge_json_rejects_non_object():
    with pytest.raises(ValueError):
        mc.merge_json("[1, 2]", SPEC)


def test_merge_toml_appends_and_does_not_duplicate():
    first = mc.merge_toml("", SPEC)
    assert first.startswith("[mcp_servers.novel-distill]")
    assert 'args = ["-m", "novel_distill", "mcp"]' in first
    assert mc.merge_toml(first, SPEC) == first

    appended = mc.merge_toml('model = "gpt"\n', SPEC)
    assert appended.startswith('model = "gpt"\n\n[mcp_servers.novel-distill]')


def test_apply_writes_backs_up_and_is_idempotent(tmp_path):
    target = tmp_path / "mcp.json"
    target.write_text('{"mcpServers": {}}', encoding="utf-8")
    entry = {"name": "测试客户端", "path": target, "kind": "json"}

    first = mc.apply([entry], SPEC)
    assert "已写入" in first[0]
    assert json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["novel-distill"] == SPEC
    assert (tmp_path / "mcp.json.bak").exists()

    second = mc.apply([entry], SPEC)
    assert "已是最新" in second[0]


def test_apply_skips_broken_json(tmp_path):
    target = tmp_path / "mcp.json"
    target.write_text("{not json", encoding="utf-8")
    res = mc.apply([{"name": "坏配置", "path": target, "kind": "json"}], SPEC)
    assert "格式无法解析" in res[0]
    assert target.read_text(encoding="utf-8") == "{not json"


def test_detect_targets_falls_back_to_project(tmp_path, monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda name: None)
    home = tmp_path / "home"
    home.mkdir()
    targets = mc.detect_targets(tmp_path / "repo", home=home)
    assert [t["id"] for t in targets] == ["project"]
    assert targets[0]["path"] == tmp_path / "repo" / ".mcp.json"


def test_detect_targets_sees_cursor_and_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda name: None)
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    (home / ".codex").mkdir()
    ids = [t["id"] for t in mc.detect_targets(tmp_path, home=home)]
    assert ids == ["cursor", "codex"]
    assert ids and mc.detect_targets(tmp_path, home=home)[0]["kind"] == "json"
