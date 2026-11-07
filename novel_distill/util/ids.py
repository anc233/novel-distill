"""稳定 ID 生成：同一本书/同一实体永远得到同一个 ID。"""

from __future__ import annotations

import hashlib
import re

from .text import norm_key

_SLUG_OK = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """ASCII 化：保留字母数字，其余转连字符；纯中文会得到空串（调用方需兜底）。"""
    s = _SLUG_OK.sub("-", (text or "").lower()).strip("-")
    return s


def stable_hash(text: str, n: int = 8) -> str:
    # 只用于生成稳定的短 ID，不做任何安全用途
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]  # noqa: S324


def entity_id(etype: str, book_slug: str, name: str) -> str:
    """实体 ID = 类型前缀 + hash(书 + 归一化名字)；同一本书内名字决定 ID。"""
    key = f"{book_slug}|{norm_key(name)}"
    return f"{etype[:4]}_{stable_hash(key)}"


def entity_id_of(etype: str, book_slug: str, name: str) -> str:
    return entity_id(etype, book_slug, name)


def relation_id(book_slug: str, src: str, dst: str, rel: str) -> str:
    """关系身份 = 书 + 起点 + 终点 + 关系名；同一对实体同一关系的多个章号合并为一条边。"""
    return "rel_" + stable_hash(f"{book_slug}|{src}|{dst}|{rel}")


def foreshadow_id(book_slug: str, title: str) -> str:
    return "fsh_" + stable_hash(f"{book_slug}|{norm_key(title)}")


def event_id(book_slug: str, chapter_idx: int, title: str) -> str:
    return "evt_" + stable_hash(f"{book_slug}|{chapter_idx}|{norm_key(title)}")


def chapter_id(book_slug: str, idx: int) -> str:
    return f"{book_slug}:c{idx:04d}"


def volume_id(book_slug: str, idx: int) -> str:
    return f"{book_slug}:v{idx:02d}"


def book_id(slug: str) -> str:
    return f"book:{slug}"


def batch_id(idx: int) -> str:
    return f"b{idx:04d}"
