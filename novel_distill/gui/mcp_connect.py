"""把 novel-distill 的 MCP server 写进本机客户端的配置文件。

原则：
- 只新增 `novel-distill` 这一条，不动别人的配置；
- 写之前先备份为 `.bak`；
- 已有同名条目就跳过，不覆盖；
- 不认识的格式宁可跳过并报告，也不猜。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

SERVER_NAME = "novel-distill"
TOML_HEADER = f"[mcp_servers.{SERVER_NAME}]"


def _toml_str(value: str) -> str:
    # JSON 的基本字符串语法与 TOML 兼容（含反斜杠转义），比手写转义安全。
    return json.dumps(value, ensure_ascii=False)


def toml_block(spec: dict[str, Any]) -> str:
    lines = [TOML_HEADER, f"command = {_toml_str(str(spec['command']))}"]
    args = ", ".join(_toml_str(str(a)) for a in spec.get("args") or [])
    lines.append(f"args = [{args}]")
    env = spec.get("env") or {}
    if env:
        pairs = ", ".join(f"{key} = {_toml_str(str(value))}" for key, value in env.items())
        lines.append(f"env = {{ {pairs} }}")
    return "\n".join(lines) + "\n"


def merge_json(existing: str, spec: dict[str, Any]) -> str:
    """把 server 条目合并进 JSON 配置文本，保留其它键。"""
    data: Any = json.loads(existing) if existing.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("配置文件顶层不是 JSON 对象")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers 不是 JSON 对象")
    servers[SERVER_NAME] = spec
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def merge_toml(existing: str, spec: dict[str, Any]) -> str:
    """把 server 追加为 TOML 表；已存在同名表则原样返回。"""
    if TOML_HEADER in existing:
        return existing
    body = existing.rstrip("\n")
    if body:
        return body + "\n\n" + toml_block(spec)
    return toml_block(spec)


def detect_targets(repo_root: Path, home: Path | None = None) -> list[dict[str, Any]]:
    """找本机可能装着、且支持 MCP 的客户端，返回要写的配置文件。"""
    home = home or Path.home()
    targets: list[dict[str, Any]] = []

    def has_dir(rel: str) -> bool:
        return (home / rel).is_dir()

    if shutil.which("claude") or has_dir(".claude"):
        targets.append(
            {
                "id": "claude-code",
                "name": "Claude Code（项目级）",
                "path": Path(repo_root) / ".mcp.json",
                "kind": "json",
            }
        )
    if has_dir(".cursor") or shutil.which("cursor"):
        targets.append(
            {"id": "cursor", "name": "Cursor", "path": home / ".cursor" / "mcp.json", "kind": "json"}
        )
    if has_dir(".codex") or shutil.which("codex"):
        targets.append(
            {"id": "codex", "name": "Codex", "path": home / ".codex" / "config.toml", "kind": "toml"}
        )
    if not targets:
        targets.append(
            {
                "id": "project",
                "name": "项目配置（未检测到客户端）",
                "path": Path(repo_root) / ".mcp.json",
                "kind": "json",
            }
        )
    return targets


def apply(targets: list[dict[str, Any]], spec: dict[str, Any]) -> list[str]:
    """按 targets 落盘，返回每一条的中文结果说明。"""
    results: list[str] = []
    for target in targets:
        name = target["name"]
        path = Path(target["path"])
        try:
            old = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError as exc:
            results.append(f"{name}: 读取失败（{exc}）")
            continue
        try:
            if target["kind"] == "toml":
                if TOML_HEADER in old:
                    results.append(f"{name}: 已存在 novel-distill，跳过（{path}）")
                    continue
                new = merge_toml(old, spec)
            else:
                new = merge_json(old, spec)
        except (ValueError, json.JSONDecodeError) as exc:
            results.append(f"{name}: 跳过，格式无法解析（{path}：{exc}）")
            continue
        if new == old:
            results.append(f"{name}: 已是最新（{path}）")
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.copy2(path, path.with_name(path.name + ".bak"))
            path.write_text(new, encoding="utf-8")
        except OSError as exc:
            results.append(f"{name}: 写入失败（{path}：{exc}）")
            continue
        results.append(f"{name}: 已写入 {path}" + ("（原文件备份为 .bak）" if old else ""))
    return results
