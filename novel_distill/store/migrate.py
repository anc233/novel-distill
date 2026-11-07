"""codex 事实源的历史迁移：改实体类型、重算 ID。

关系/出场/证据都以实体名字引用，因此改 ID 不会断链；改完必须 rebuild-db + render。
"""

from __future__ import annotations

from pathlib import Path

from ..codex.protocol import ENTITY_TYPES
from ..util.ids import entity_id
from ..util.text import norm_key
from . import jsonl


def find_entity(rows: list[dict], name: str) -> dict | None:
    key = norm_key(name)
    for r in rows:
        if norm_key(r.get("name") or "") == key:
            return r
    for r in rows:
        if any(norm_key(a) == key for a in (r.get("aliases") or [])):
            return r
    return None


def retype(book_dir: str | Path, name: str, new_etype: str, book: str | None = None, dry_run: bool = False) -> dict:
    """把某个实体改成新类型（如 material → pill），并重算 id。返回迁移报告。"""
    if new_etype not in ENTITY_TYPES:
        raise ValueError(f"未知实体类型：{new_etype}；可用：{', '.join(ENTITY_TYPES)}")
    book_dir = Path(book_dir)
    rows = jsonl.read_jsonl(jsonl.path_for(book_dir, "entities"))
    if book is None:
        book = book_dir.name
    rec = find_entity(rows, name)
    if rec is None:
        raise FileNotFoundError(f"没有找到实体：{name}")
    old_etype = rec.get("etype")
    old_id = rec.get("id")
    new_id = entity_id(new_etype, book, rec["name"])
    if old_etype == new_etype and old_id == new_id:
        return {"changed": False, "name": rec["name"], "etype": new_etype, "id": new_id, "dry_run": dry_run}
    updated = {**rec, "etype": new_etype, "id": new_id}
    if not dry_run:
        out = [updated if r is rec else r for r in rows]
        jsonl.replace_all(book_dir, "entities", out)
    return {
        "changed": True,
        "name": rec["name"],
        "old_etype": old_etype,
        "new_etype": new_etype,
        "old_id": old_id,
        "new_id": new_id,
        "dry_run": dry_run,
    }


def retype_many(book_dir: str | Path, pairs: list[tuple[str, str]], book: str | None = None, dry_run: bool = False) -> dict:
    done = [retype(book_dir, name, etype, book=book, dry_run=dry_run) for name, etype in pairs]
    return {"book_dir": str(book_dir), "changed": [d for d in done if d["changed"]], "unchanged": [d for d in done if not d["changed"]]}
