"""codex/*.jsonl：唯一事实源。写入是「按键合并 + 原子替换」，保证幂等与可 diff。"""

from __future__ import annotations

import json
import os
from pathlib import Path

FILES = {
    "entities": "entities.jsonl",
    "relations": "relations.jsonl",
    "evidence": "evidence.jsonl",
    "foreshadowings": "foreshadowings.jsonl",
    "events": "events.jsonl",
    "appearances": "appearances.jsonl",
    "summaries": "summaries.jsonl",
    "conflicts": "conflicts.jsonl",
    "anomalies": "anomalies.jsonl",
    "batches": "batches.jsonl",
}

KEYS = {
    "entities": ("id",),
    "relations": ("book", "src", "dst", "rel"),
    "evidence": ("book", "entity", "chapter", "quote"),
    "foreshadowings": ("id",),
    "events": ("id",),
    "appearances": ("book", "entity", "chapter"),
    "summaries": ("book", "scope", "ref"),
    "conflicts": ("id",),
    "anomalies": ("book", "kind", "chapter", "detail"),
    "batches": ("id",),
}


def codex_dir(book_dir: str | Path) -> Path:
    d = Path(book_dir) / "codex"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(book_dir: str | Path, kind: str) -> Path:
    return codex_dir(book_dir) / FILES[kind]


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{lineno} JSON 解析失败：{exc}") from exc
    return out


def key_of(kind: str, rec: dict) -> tuple:
    parts = tuple(rec.get(k) for k in KEYS[kind])
    if any(p is None or p == "" for p in parts):
        raise ValueError(f"{kind} 记录缺少主键字段 {KEYS[kind]}：{rec}")
    return tuple(str(p) for p in parts)


def _atomic_write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
        if lines:
            fh.write("\n")
    os.replace(tmp, path)


def _merge_relation(old: dict, new: dict) -> dict:
    """同一对实体同一关系：章号取最早，备注取较晚出现的那条。"""
    old_ch = old.get("chapter") or 0
    new_ch = new.get("chapter") or 0
    merged = {**old, **new}
    chapters = [c for c in (old.get("chapter"), new.get("chapter")) if c]
    merged["chapter"] = min(chapters) if chapters else None
    later, earlier = (new, old) if new_ch >= old_ch else (old, new)
    merged["note"] = later.get("note") or earlier.get("note") or ""
    merged["id"] = new.get("id") or old.get("id")
    return merged


def renormalize_relations(book_dir: str | Path) -> int:
    """一次性迁移：把带章号旧 ID 的关系行按新主键合并重写。返回最终条数。"""
    from ..util.ids import relation_id

    p = path_for(book_dir, "relations")
    grouped: dict[tuple, dict] = {}
    for rec in read_jsonl(p):
        key = (rec.get("book") or "", rec.get("src") or "", rec.get("dst") or "", rec.get("rel") or "相关")
        rec = {**rec, "id": relation_id(key[0], key[1], key[2], key[3])}
        grouped[key] = _merge_relation(grouped[key], rec) if key in grouped else rec
    lines = [json.dumps(grouped[k], ensure_ascii=False, sort_keys=True) for k in sorted(grouped)]
    _atomic_write(p, lines)
    return len(grouped)


def upsert_many(book_dir: str | Path, kind: str, records: list[dict]) -> int:
    """按键合并写入；返回文件最终条数。顺序按 key 排序，保证 diff 稳定。"""
    p = path_for(book_dir, kind)
    existing = {key_of(kind, r): r for r in read_jsonl(p)}
    for rec in records:
        key = key_of(kind, rec)
        if kind == "relations" and key in existing:
            existing[key] = _merge_relation(existing[key], rec)
        else:
            existing[key] = rec
    lines = [json.dumps(existing[k], ensure_ascii=False, sort_keys=True) for k in sorted(existing)]
    _atomic_write(p, lines)
    return len(existing)


def replace_all(book_dir: str | Path, kind: str, rows: list[dict]) -> int:
    """整体替换某类记录（迁移用）。按主键排序后原子写入。"""
    p = path_for(book_dir, kind)
    rows = sorted(rows, key=lambda r: key_of(kind, r))
    _atomic_write(p, [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows])
    return len(rows)


def count(book_dir: str | Path, kind: str) -> int:
    return len(read_jsonl(path_for(book_dir, kind)))


def prune(book_dir: str | Path) -> dict[str, int]:
    """清理主键残缺的历史记录（协议升级后用）。返回每种记录被丢弃的条数。"""
    dropped: dict[str, int] = {}
    for kind in FILES:
        p = path_for(book_dir, kind)
        rows = read_jsonl(p)
        keep: list[dict] = []
        bad = 0
        for r in rows:
            try:
                key_of(kind, r)
            except ValueError:
                bad += 1
                continue
            keep.append(r)
        if bad:
            dropped[kind] = bad
            keep.sort(key=lambda r: key_of(kind, r))
            _atomic_write(p, [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in keep])
    return dropped
