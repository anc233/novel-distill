"""用 obsidiantools 读渲染产物，校验 Obsidian 双链是否闭合。

Obsidian 按路径后缀解析双链：`[[修仙蒸馏/凡人修仙传/01 角色/韩立|韩立]]`、
`[[01 角色/韩立]]`、`[[韩立]]` 都指向同一个笔记。所以这里不做字符串全等比较，
而是把目标逐层剥掉前缀后跟笔记相对路径比对；孤立笔记也按解析后的连边统计，
不用 obsidiantools 自带的 isolated_notes（它按全等匹配，会把路径式链接当断链）。

只读，不改 vault。obsidiantools 是可选依赖（extras: vault）；未安装时返回
available=False，调用方（lint）跳过这一项而不是崩溃。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

# 标准 Markdown 链接：[显示](目标) 或 [显示](<带空格的目标>)
_MD_LINK = re.compile(r"\[[^\]]*\]\((<[^>]+>|[^)\n]+)\)")


def _norm(target: str) -> str:
    """把 `a/b#锚点|别名` 归一成 `a/b`：去别名、去锚点、去 .md、统一斜杠。"""
    text = (target or "").replace("\\", "/").strip()
    text = text.split("|", 1)[0]
    text = text.split("#", 1)[0]
    return text.removesuffix(".md").strip("/")


def _markdown_targets(path: Path) -> list[str]:
    """读出笔记里的标准 Markdown 链接目标（跳过 http(s)、锚点、图片）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for raw in _MD_LINK.findall(text):
        target = unquote(raw.strip().strip("<>")).split("#", 1)[0].strip()
        if not target or target.startswith(("#", "/")) or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            continue
        out.append(target)
    return out


def check_vault(vault_root: str | Path, *, markdown_links: bool = True) -> dict:
    """扫描一个 Obsidian 目录（或它的子目录），返回断链与孤立笔记。

    返回：
        available    obsidiantools 是否可用且目录存在
        notes        参与检查的笔记数
        links        能解析到的双链条数
        broken_links [{note, target}]：note 里写了 [[target]] 但 vault 里没有对应笔记
        orphan_notes 没有任何双链进出的笔记名
    """
    root = Path(vault_root)
    if not root.is_dir():
        return {"available": False, "reason": f"目录不存在：{root}", "notes": 0}
    try:
        import obsidiantools.api as ot
    except ImportError:
        return {"available": False, "reason": '未安装 obsidiantools（pip install "novel-distill[vault]"）', "notes": 0}

    vault = ot.Vault(root)
    vault.gather()
    vault.connect()

    relpaths = {p.relative_to(root).as_posix()[:-3] for p in root.rglob("*.md")}
    by_path = set(relpaths)
    by_stem: dict[str, str] = {}
    for rel in relpaths:
        by_stem.setdefault(rel.rsplit("/", 1)[-1], rel)

    def resolve(target: str) -> str | None:
        """把链接目标解析成 vault 内的相对路径（不含 .md），解析不到返回 None。"""
        text = _norm(target)
        if not text:
            return None
        if text in by_path:
            return text
        parts = text.split("/")
        # 链接比笔记路径长：逐层剥前缀（[[修仙蒸馏/凡人修仙传/01 角色/韩立]] → 01 角色/韩立）
        for i in range(1, len(parts)):
            candidate = "/".join(parts[i:])
            if candidate in by_path:
                return candidate
        # 链接比笔记路径短或同名：按末段文件名回退（[[韩立]]）
        return by_stem.get(parts[-1])

    broken: list[dict] = []
    linked: set[str] = set()
    links = 0
    for note, targets in (vault.wikilinks_index or {}).items():
        src = resolve(note)
        if src is None:
            continue
        for target in targets:
            dst = resolve(target)
            if dst is None:
                broken.append({"note": note, "target": target})
            else:
                links += 1
                linked.add(src)
                linked.add(dst)

    if markdown_links:
        # --plain-links 渲染出的是标准 Markdown 相对链接，不解析它们会把所有笔记误判成孤立
        root_abs = root.resolve()
        for path in root.rglob("*.md"):
            note = path.relative_to(root).as_posix()[:-3]
            for target in _markdown_targets(path):
                if not target.lower().endswith(".md"):
                    continue
                dest = (path.parent / target).resolve()
                try:
                    dest_rel = dest.relative_to(root_abs).as_posix()[:-3]
                except ValueError:
                    broken.append({"note": note, "target": target})
                    continue
                if dest_rel in by_path:
                    links += 1
                    linked.add(note)
                    linked.add(dest_rel)
                else:
                    broken.append({"note": note, "target": target})

    return {
        "available": True,
        "vault": str(root),
        "notes": len(relpaths),
        "links": links,
        "broken_links": broken,
        "orphan_notes": sorted(rel for rel in relpaths if rel not in linked),
    }
