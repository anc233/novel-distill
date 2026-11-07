"""仓储层：把 codex 记录写进 SQLite，并提供查询。所有函数只操作传入的连接，不自行提交。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ..util.ids import entity_id, event_id, foreshadow_id, relation_id, stable_hash
from ..util.text import count_chars, norm_key
from .db import now_iso

ENTITY_TYPES = (
    "world_rule", "faction", "character", "monster", "dungeon", "arc",
    "technique", "artifact", "material", "pill", "realm",
)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def ensure_book(
    conn,
    *,
    slug: str,
    title: str,
    author: str = "",
    sha256: str = "",
    encoding: str = "",
    total_chars: int = 0,
) -> None:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO books (slug, title, author, source_sha256, source_encoding, total_chars, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            title = excluded.title,
            author = excluded.author,
            source_sha256 = excluded.source_sha256,
            source_encoding = excluded.source_encoding,
            total_chars = excluded.total_chars,
            updated_at = excluded.updated_at
        """,
        (slug, title, author, sha256, encoding, total_chars, ts, ts),
    )


def replace_structure(conn, slug: str, volumes: Iterable[dict], chapters: Iterable[dict]) -> tuple[int, int]:
    """整本替换卷/章（含正文）。用于 add 与 rebuild。"""
    conn.execute("DELETE FROM volumes WHERE book_slug = ?", (slug,))
    conn.execute("DELETE FROM chapters WHERE book_slug = ?", (slug,))
    vn = 0
    for v in volumes:
        conn.execute(
            """
            INSERT INTO volumes (book_slug, idx, number, title, raw_heading, start_chapter_idx,
                                 end_chapter_idx, chapter_count, char_count, implicit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug, int(v["idx"]), v.get("number"), v.get("title") or "", v.get("raw_heading") or "",
                int(v.get("start_chapter_idx") or 0), int(v.get("end_chapter_idx") or 0),
                int(v.get("chapter_count") or 0), int(v.get("char_count") or 0),
                1 if v.get("implicit") else 0,
            ),
        )
        vn += 1
    cn = 0
    for c in chapters:
        conn.execute(
            """
            INSERT INTO chapters (book_slug, idx, volume_idx, number, number_raw, title, raw_heading, char_count, body)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug, int(c["idx"]), int(c.get("volume_idx") or 1), c.get("number"),
                str(c.get("number_raw") or ""), c.get("title") or "", c.get("raw_heading") or "",
                int(c.get("char_count") or count_chars(c.get("body") or "")), c.get("body") or "",
            ),
        )
        cn += 1
    return vn, cn


def clear_codex(conn, book: str) -> None:
    """清空一本书的全部设定类数据（不碰 books/volumes/chapters），供 rebuild 重建。"""
    conn.execute(
        "DELETE FROM aliases WHERE entity_id IN (SELECT id FROM entities WHERE book_slug = ?)", (book,)
    )
    for table in (
        "appearances", "relations", "evidence", "foreshadowings", "events",
        "summaries", "conflicts", "anomalies", "batches", "entities",
    ):
        # table 来自上面的硬编码元组，不接受外部输入
        conn.execute(f"DELETE FROM {table} WHERE book_slug = ?", (book,))  # noqa: S608


def upsert_entity(conn, book: str, rec: dict) -> str:
    """写入实体并同步别名；返回实体 ID。"""
    etype = rec.get("etype") or rec.get("type") or "concept"
    name = (rec.get("name") or "").strip()
    if not name:
        raise ValueError(f"实体缺少 name：{rec}")
    eid = rec.get("id") or entity_id(etype, book, name)
    ts = now_iso()
    aliases = [a.strip() for a in (rec.get("aliases") or []) if a and a.strip()]

    # 增量合并：后一批只补充自己读到的东西，不能抹掉前一批的人物设定。
    old = conn.execute("SELECT * FROM entities WHERE id = ?", (eid,)).fetchone()
    old_data = json.loads(old["data"]) if old is not None and old["data"] else {}
    new_data = rec.get("data") or {}
    merged_data = {**old_data, **{k: v for k, v in new_data.items() if v not in (None, "", [], {})}}

    imp = int(rec.get("importance") or 3)
    first = rec.get("first_chapter")
    last = rec.get("last_chapter")
    if old is not None:
        imp = max(imp, int(old["importance"] or 0))
        if old["first_chapter_idx"] is not None:
            first = min(first, old["first_chapter_idx"]) if first is not None else old["first_chapter_idx"]
        if old["last_chapter_idx"] is not None:
            last = max(last, old["last_chapter_idx"]) if last is not None else old["last_chapter_idx"]
    summary = rec.get("summary") or (old["summary"] if old is not None else "")
    status = rec.get("status") or (old["status"] if old is not None else "active")

    conn.execute(
        """
        INSERT INTO entities (id, book_slug, etype, name, importance, status, summary,
                              first_chapter_idx, last_chapter_idx, data, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            etype = excluded.etype,
            name = excluded.name,
            importance = excluded.importance,
            status = excluded.status,
            summary = excluded.summary,
            first_chapter_idx = excluded.first_chapter_idx,
            last_chapter_idx = excluded.last_chapter_idx,
            data = excluded.data,
            updated_at = excluded.updated_at
        """,
        (eid, book, etype, name, imp, status, summary, first, last, _json(merged_data), ts, ts),
    )
    for alias in aliases:
        conn.execute(
            "INSERT OR IGNORE INTO aliases (entity_id, alias, source) VALUES (?, ?, ?)",
            (eid, alias, rec.get("batch") or "codex"),
        )
    return eid


def compute_spans(appearances=(), evidence=(), relations=(), events=()) -> dict[str, tuple[int, int]]:
    """从出场/证据/关系/事件里收集每个实体的章号跨度 [最小, 最大]。"""
    spans: dict[str, list[int]] = {}

    def add(name, ch) -> None:
        if not name or ch is None:
            return
        ch = int(ch)
        if ch <= 0:
            return
        cur = spans.get(name)
        if cur is None:
            spans[name] = [ch, ch]
        else:
            cur[0] = min(cur[0], ch)
            cur[1] = max(cur[1], ch)

    for a in appearances:
        add(a.get("entity"), a.get("chapter"))
    for e in evidence:
        add(e.get("entity"), e.get("chapter"))
    for r in relations:
        add(r.get("src"), r.get("chapter"))
        add(r.get("dst"), r.get("chapter"))
    for ev in events:
        for p in ev.get("participants") or []:
            add(p, ev.get("chapter"))
    return {k: (v[0], v[1]) for k, v in spans.items()}


def apply_spans(conn, book: str, spans: dict[str, tuple[int, int]]) -> int:
    """把章号跨度写回实体（只扩不缩）。返回更新的实体数。"""
    ts = now_iso()
    updated = 0
    for name, (lo, hi) in spans.items():
        ent = resolve_entity(conn, book, name)
        if ent is None:
            continue
        conn.execute(
            """
            UPDATE entities
               SET first_chapter_idx = CASE WHEN first_chapter_idx IS NULL OR first_chapter_idx > ? THEN ? ELSE first_chapter_idx END,
                   last_chapter_idx  = CASE WHEN last_chapter_idx IS NULL OR last_chapter_idx < ? THEN ? ELSE last_chapter_idx END,
                   updated_at = ?
             WHERE id = ?
            """,
            (lo, lo, hi, hi, ts, ent["id"]),
        )
        updated += 1
    return updated


def resolve_entity(conn, book: str, name: str):
    """按正式名或别名找实体；找不到返回 None。"""
    key = norm_key(name)
    row = conn.execute(
        "SELECT * FROM entities WHERE book_slug = ? AND name = ? LIMIT 1", (book, name)
    ).fetchone()
    if row:
        return row
    cands = conn.execute(
        """
        SELECT DISTINCT e.* FROM entities e
        LEFT JOIN aliases a ON a.entity_id = e.id
        WHERE e.book_slug = ? AND (e.name = ? OR a.alias = ?)
        ORDER BY e.importance DESC
        """,
        (book, name, name),
    ).fetchall()
    for cand in cands:
        if norm_key(cand["name"]) == key:
            return cand
        aliases = conn.execute("SELECT alias FROM aliases WHERE entity_id = ?", (cand["id"],)).fetchall()
        if any(norm_key(a["alias"]) == key for a in aliases):
            return cand
    return None


def upsert_relation(conn, book: str, rec: dict) -> tuple[str, str | None]:
    """写入关系（src/dst 用名字）。返回 (状态, 关系ID)；状态 ∈ ok/unresolved。"""
    src_name = (rec.get("src") or rec.get("from") or "").strip()
    dst_name = (rec.get("dst") or rec.get("to") or "").strip()
    src = resolve_entity(conn, book, src_name) if src_name else None
    dst = resolve_entity(conn, book, dst_name) if dst_name else None
    if src is None or dst is None:
        return "unresolved", None
    rel = rec.get("rel") or "相关"
    rid = rec.get("id") or relation_id(book, src["id"], dst["id"], rel)
    conn.execute(
        """
        INSERT INTO relations (id, book_slug, src_id, dst_id, rel, note, chapter_idx, confidence, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            rel = excluded.rel, note = excluded.note, confidence = excluded.confidence, data = excluded.data,
            chapter_idx = MIN(COALESCE(relations.chapter_idx, excluded.chapter_idx), COALESCE(excluded.chapter_idx, relations.chapter_idx))
        """,
        (
            rid, book, src["id"], dst["id"], rel, rec.get("note") or "",
            rec.get("chapter"), float(rec.get("confidence") or 1.0), _json(rec.get("data")),
        ),
    )
    return "ok", rid


def add_evidence(conn, book: str, rec: dict, batch: str = "") -> bool:
    """证据落库；同名同章的原文引用只留一条。实体名找不到时 entity_id 记空串。"""
    name = (rec.get("entity") or "").strip()
    ent = resolve_entity(conn, book, name) if name else None
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO evidence (book_slug, entity_id, chapter_idx, kind, quote, batch, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            book, ent["id"] if ent else "", int(rec.get("chapter") or 0),
            rec.get("kind") or "", (rec.get("quote") or "").strip(),
            rec.get("batch") or batch, now_iso(),
        ),
    )
    return cur.rowcount > 0


def add_appearance(conn, book: str, entity_id_value: str, chapter_idx: int, role: str = "", weight: float = 1.0) -> None:
    conn.execute(
        """
        INSERT INTO appearances (entity_id, book_slug, chapter_idx, role, weight)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(entity_id, chapter_idx) DO UPDATE SET role = excluded.role, weight = excluded.weight
        """,
        (entity_id_value, book, int(chapter_idx), role, float(weight)),
    )


def upsert_foreshadowing(conn, book: str, rec: dict) -> str:
    title = (rec.get("title") or "").strip()
    fid = rec.get("id") or foreshadow_id(book, title)
    conn.execute(
        """
        INSERT INTO foreshadowings (id, book_slug, title, status, planted_chapter_idx, paid_chapter_idx, detail, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, status = excluded.status,
            paid_chapter_idx = COALESCE(excluded.paid_chapter_idx, foreshadowings.paid_chapter_idx),
            detail = excluded.detail, data = excluded.data
        """,
        (
            fid, book, title, rec.get("status") or "open", rec.get("planted_chapter"),
            rec.get("paid_chapter"), rec.get("detail") or "", _json(rec.get("data")),
        ),
    )
    return fid


def upsert_event(conn, book: str, rec: dict) -> str:
    title = (rec.get("title") or "").strip()
    eid = rec.get("id") or event_id(book, int(rec.get("chapter") or 0), title)
    conn.execute(
        """
        INSERT INTO events (id, book_slug, chapter_idx, title, participants, detail, importance, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, participants = excluded.participants,
            detail = excluded.detail, importance = excluded.importance, data = excluded.data
        """,
        (
            eid, book, rec.get("chapter"), title,
            _json(rec.get("participants") or []), rec.get("detail") or "",
            int(rec.get("importance") or 3), _json(rec.get("data")),
        ),
    )
    return eid


def upsert_summary(conn, book: str, rec: dict) -> None:
    text = rec.get("text") or ""
    conn.execute(
        """
        INSERT INTO summaries (book_slug, scope, ref_idx, text, char_count, batch)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(book_slug, scope, ref_idx) DO UPDATE SET
            text = excluded.text, char_count = excluded.char_count, batch = excluded.batch
        """,
        (book, rec.get("scope") or "chapter", int(rec.get("ref") or 0), text, count_chars(text), rec.get("batch") or ""),
    )


def upsert_conflict(conn, book: str, rec: dict) -> str:
    cid = rec.get("id") or "cfl_" + stable_hash(
        f"{book}|{rec.get('kind')}|{rec.get('entity')}|{rec.get('other')}"
    )
    conn.execute(
        """
        INSERT INTO conflicts (id, book_slug, kind, entity_id, other, detail, status, created_at, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            detail = excluded.detail,
            status = excluded.status,
            resolved_at = excluded.resolved_at
        """,
        (
            cid, book, rec.get("kind") or "", rec.get("entity_id") or rec.get("entity") or "",
            rec.get("other") or "", rec.get("detail") or "", rec.get("status") or "open",
            rec.get("created_at") or now_iso(), rec.get("resolved_at"),
        ),
    )
    return cid


def add_anomalies(conn, book: str, anomalies: Iterable[dict]) -> int:
    n = 0
    ts = now_iso()
    for a in anomalies:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO anomalies (book_slug, kind, chapter_idx, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (book, a.get("kind") or "", int(a.get("chapter_idx") or 0), a.get("detail") or "", ts),
        )
        n += cur.rowcount
    return n


def upsert_batch(conn, book: str, rec: dict) -> None:
    conn.execute(
        """
        INSERT INTO batches (id, book_slug, start_chapter_idx, end_chapter_idx, status,
                             packet_path, result_path, tokens_est, created_at, applied_at, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status, packet_path = excluded.packet_path, result_path = excluded.result_path,
            tokens_est = excluded.tokens_est, applied_at = excluded.applied_at, error = excluded.error
        """,
        (
            rec["id"], book, int(rec.get("start_chapter") or 0), int(rec.get("end_chapter") or 0),
            rec.get("status") or "pending", rec.get("packet_path") or "", rec.get("result_path") or "",
            int(rec.get("tokens_est") or 0), rec.get("created_at") or now_iso(), rec.get("applied_at"),
            rec.get("error") or "",
        ),
    )


def get_entity(conn, book: str, name: str) -> dict | None:
    row = resolve_entity(conn, book, name)
    if row is None:
        return None
    aliases = [a["alias"] for a in conn.execute("SELECT alias FROM aliases WHERE entity_id = ? ORDER BY alias", (row["id"],))]
    ev = conn.execute(
        "SELECT chapter_idx, kind, quote FROM evidence WHERE book_slug = ? AND entity_id = ? ORDER BY chapter_idx",
        (book, row["id"]),
    ).fetchall()
    data = json.loads(row["data"] or "{}")
    return {
        "id": row["id"],
        "etype": row["etype"],
        "name": row["name"],
        "aliases": aliases,
        "importance": row["importance"],
        "status": row["status"],
        "summary": row["summary"],
        "first_chapter": row["first_chapter_idx"],
        "last_chapter": row["last_chapter_idx"],
        "data": data,
        "evidence": [dict(e) for e in ev],
    }


def list_entities(conn, book: str, etype: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT id, etype, name, importance, status, summary, first_chapter_idx, last_chapter_idx FROM entities WHERE book_slug = ?"
    params: list[Any] = [book]
    if etype:
        sql += " AND etype = ?"
        params.append(etype)
    sql += " ORDER BY importance DESC, name LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def search_chapters(conn, book: str, query: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.idx, c.title, c.number, snippet(chapters_fts, 0, '[', ']', '…', 12) AS snip
        FROM chapters_fts JOIN chapters c ON c.rowid = chapters_fts.rowid
        WHERE chapters_fts MATCH ? AND c.book_slug = ?
        ORDER BY rank LIMIT ?
        """,
        (query, book, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def stats(conn, book: str) -> dict:
    def one(sql: str) -> int:
        return conn.execute(sql, (book,)).fetchone()[0]

    by_type = {
        r["etype"]: r["n"]
        for r in conn.execute(
            "SELECT etype, COUNT(*) AS n FROM entities WHERE book_slug = ? GROUP BY etype ORDER BY n DESC", (book,)
        )
    }
    foreshadow = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM foreshadowings WHERE book_slug = ? GROUP BY status", (book,)
        )
    }
    return {
        "book": book,
        "chapters": one("SELECT COUNT(*) FROM chapters WHERE book_slug = ?"),
        "volumes": one("SELECT COUNT(*) FROM volumes WHERE book_slug = ?"),
        "entities": one("SELECT COUNT(*) FROM entities WHERE book_slug = ?"),
        "entities_by_type": by_type,
        "relations": one("SELECT COUNT(*) FROM relations WHERE book_slug = ?"),
        "evidence": one("SELECT COUNT(*) FROM evidence WHERE book_slug = ?"),
        "foreshadowings": foreshadow,
        "events": one("SELECT COUNT(*) FROM events WHERE book_slug = ?"),
        "summaries": one("SELECT COUNT(*) FROM summaries WHERE book_slug = ?"),
        "conflicts_open": one("SELECT COUNT(*) FROM conflicts WHERE book_slug = ? AND status = 'open'"),
        "anomalies": one("SELECT COUNT(*) FROM anomalies WHERE book_slug = ?"),
        "batches_applied": one("SELECT COUNT(*) FROM batches WHERE book_slug = ? AND status = 'applied'"),
    }
