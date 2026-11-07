"""全局配置与路径：默认参数集中在这里，CLI 全部可覆盖。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
# PyInstaller 单文件 exe 下 __file__ 指向临时解包目录（_MEIxxxx），
# 用它推工作区会把数据写进 Temp；此时以 exe 自身所在目录为"仓库根"，便携且可预期。
FROZEN = bool(getattr(sys, "frozen", False))
REPO_ROOT = Path(sys.executable).resolve().parent if FROZEN else PACKAGE_ROOT.parent
# 环境变量优先（便携包/多项目共用一个 exe 时用），否则落在程序同级的 workspace/。
WORKSPACE = Path(os.environ.get("NOVEL_DISTILL_WORKSPACE") or (REPO_ROOT / "workspace"))

# 默认落到程序同级的 vault/（渲染时自动创建）——没装 Obsidian 也能用，
# 任何 markdown 编辑器都能打开；装了 Obsidian 则优先用 obsidian.json 里的 vault。
DEFAULT_VAULT = REPO_ROOT / "vault"
VAULT_SUBDIR = "修仙蒸馏"

DEFAULT_BATCH_CHAPTERS = 5
MAX_CHAPTER_CHARS = 8000
MAX_PACKET_CHARS = 40000
CHARS_PER_TOKEN = 1.5

SCHEMA_VERSION = 1


def book_dir(slug: str, workdir: str | Path | None = None) -> Path:
    return Path(workdir or WORKSPACE) / slug


def db_path(slug: str, workdir: str | Path | None = None) -> Path:
    return book_dir(slug, workdir) / "book.db"


def obsidian_vaults() -> list[Path]:
    """从 Obsidian 的配置里读出所有 vault 路径。"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    cfg = Path(appdata) / "obsidian" / "obsidian.json"
    if not cfg.exists():
        return []
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - obsidian.json 由用户手改，格式不可信
        return []
    vaults = [info for info in (data.get("vaults") or {}).values() if info.get("path")]
    # 当前打开的 vault 排最前：用户手动改过 obsidian.json 时顺序不可信。
    vaults.sort(key=lambda info: not info.get("open"))
    return [Path(info["path"]) for info in vaults]


def resolve_vault(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("NOVEL_DISTILL_VAULT")
    if env:
        return Path(env)
    if DEFAULT_VAULT.exists():
        return DEFAULT_VAULT
    vaults = obsidian_vaults()
    if vaults:
        return vaults[0]
    return DEFAULT_VAULT
