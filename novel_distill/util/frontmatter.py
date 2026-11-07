"""极简 frontmatter 读写：只支持 importer 自己写出的形态（key: JSON 值）。"""

from __future__ import annotations

import json


def parse(text: str) -> tuple[dict, str]:
    """返回 (meta, body)。没有 frontmatter 时 meta={}。"""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        try:
            meta[k.strip()] = json.loads(v)
        except json.JSONDecodeError:
            meta[k.strip()] = v
    return meta, "\n".join(lines[end + 1 :])


def strip_chapter_body(body: str) -> str:
    """去掉渲染用的一级标题行，得到与切章时一致的正文。"""
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return "\n".join(lines[i:]).strip("\n")
