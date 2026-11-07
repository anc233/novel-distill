"""配置与路径：单文件 exe 下工作区必须落在 exe 旁边，而不是临时解包目录。"""

import importlib
import json
import sys

from novel_distill import config


def test_frozen_uses_executable_dir(monkeypatch, tmp_path):
    exe = tmp_path / "novel-distill.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    try:
        reloaded = importlib.reload(config)
        root = tmp_path.resolve()
        workspace = root / "workspace"
        assert reloaded.FROZEN is True
        assert (root, workspace) == (reloaded.REPO_ROOT, reloaded.WORKSPACE)
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_env_overrides_workspace_and_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_DISTILL_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("NOVEL_DISTILL_VAULT", str(tmp_path / "vault"))
    try:
        reloaded = importlib.reload(config)
        assert (reloaded.WORKSPACE, reloaded.resolve_vault()) == (tmp_path / "ws", tmp_path / "vault")
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_script_mode_uses_package_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    reloaded = importlib.reload(config)
    assert reloaded.FROZEN is False
    assert reloaded.WORKSPACE == reloaded.REPO_ROOT / "workspace"
    assert (reloaded.REPO_ROOT / "novel_distill").is_dir()

def test_default_vault_is_portable(monkeypatch):
    """默认 vault 必须在程序同级目录，否则别人机器上会去找不存在的盘符。"""
    monkeypatch.delenv("NOVEL_DISTILL_VAULT", raising=False)
    try:
        reloaded = importlib.reload(config)
        assert reloaded.DEFAULT_VAULT == reloaded.REPO_ROOT / "vault"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_obsidian_vaults_prefers_open(monkeypatch, tmp_path):
    appdata = tmp_path / "appdata"
    cfgdir = appdata / "obsidian"
    cfgdir.mkdir(parents=True)
    payload = {
        "vaults": {
            "aaa": {"path": str(tmp_path / "closed"), "open": False},
            "bbb": {"path": str(tmp_path / "opened"), "open": True},
        }
    }
    (cfgdir / "obsidian.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    try:
        reloaded = importlib.reload(config)
        assert reloaded.obsidian_vaults()[0] == tmp_path / "opened"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
