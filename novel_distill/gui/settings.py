"""GUI 设置：默认写在程序同级目录（便携包解压即用）。"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config

FILENAME = "novel_distill_gui.json"


def settings_path() -> Path:
    return config.REPO_ROOT / FILENAME


def load_settings() -> dict:
    data: dict = {}
    path = settings_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
    data.setdefault("lang", "zh")
    data.setdefault("workspace", "")
    data.setdefault("vault", "")
    data.setdefault("readonly", False)
    data.setdefault("geometry", "")
    return data


def save_settings(data: dict) -> Path:
    path = settings_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
