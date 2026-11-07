"""一次性数据修复：按证据/关系/事件/出场重算实体章号跨度（只认真正出现的章）。"""

from __future__ import annotations

from pathlib import Path

from . import jsonl


def recompute_entity_spans(book_dir: str | Path, dry_run: bool = False) -> dict:
    book_dir = Path(book_dir)
    entities = jsonl.read_jsonl(jsonl.path_for(book_dir, "entities"))
    mentioned: dict[str, set[int]] = {}

    def touch(name: str, ch) -> None:
        name = (name or "").strip()
        try:
            ch = int(ch)
        except (TypeError, ValueError):
            return
        if name and ch:
            mentioned.setdefault(name, set()).add(ch)

    for ev in jsonl.read_jsonl(jsonl.path_for(book_dir, "evidence")):
        touch(ev.get("entity"), ev.get("chapter"))
    for rel in jsonl.read_jsonl(jsonl.path_for(book_dir, "relations")):
        touch(rel.get("src"), rel.get("chapter"))
        touch(rel.get("dst"), rel.get("chapter"))
    for evt in jsonl.read_jsonl(jsonl.path_for(book_dir, "events")):
        for p in evt.get("participants") or []:
            touch(p, evt.get("chapter"))
    for ap in jsonl.read_jsonl(jsonl.path_for(book_dir, "appearances")):
        touch(ap.get("entity"), ap.get("chapter"))

    changes = []
    for rec in entities:
        keys = [rec.get("name"), *list(rec.get("aliases") or [])]
        chs: set[int] = set()
        for k in keys:
            chs |= mentioned.get((k or "").strip(), set())
        if not chs:
            continue
        first, last = min(chs), max(chs)
        if rec.get("first_chapter") != first or rec.get("last_chapter") != last:
            changes.append({"name": rec.get("name"), "old": [rec.get("first_chapter"), rec.get("last_chapter")], "new": [first, last]})
            rec["first_chapter"] = first
            rec["last_chapter"] = last
    if changes and not dry_run:
        jsonl.replace_all(book_dir, "entities", entities)
    return {"book_dir": str(book_dir), "scanned": len(entities), "changed": len(changes), "changes": changes, "dry_run": dry_run}
