"""按卷 / 按章查询：把「这一卷/这一章到底有什么」一次查全。"""

from __future__ import annotations


def volume(conn, slug: str, idx: int) -> dict | None:
    v = conn.execute("SELECT * FROM volumes WHERE book_slug = ? AND idx = ?", (slug, idx)).fetchone()
    if v is None:
        return None
    chapters = conn.execute(
        """
        SELECT c.idx, c.title, c.char_count,
               CASE WHEN s.text IS NULL THEN 0 ELSE 1 END AS summarized
        FROM chapters c
        LEFT JOIN summaries s ON s.book_slug = c.book_slug AND s.scope = 'chapter' AND s.ref_idx = c.idx
        WHERE c.book_slug = ? AND c.idx BETWEEN ? AND ?
        ORDER BY c.idx
        """,
        (slug, v["start_chapter_idx"], v["end_chapter_idx"]),
    ).fetchall()
    ents = conn.execute(
        """
        SELECT name, etype, importance, first_chapter_idx, last_chapter_idx
        FROM entities
        WHERE book_slug = ? AND first_chapter_idx IS NOT NULL
          AND first_chapter_idx <= ? AND COALESCE(last_chapter_idx, first_chapter_idx) >= ?
        ORDER BY importance DESC, first_chapter_idx, name
        """,
        (slug, v["end_chapter_idx"], v["start_chapter_idx"]),
    ).fetchall()
    fs = conn.execute(
        "SELECT title, status, planted_chapter_idx FROM foreshadowings "
        "WHERE book_slug = ? AND planted_chapter_idx BETWEEN ? AND ? ORDER BY planted_chapter_idx",
        (slug, v["start_chapter_idx"], v["end_chapter_idx"]),
    ).fetchall()
    events = conn.execute(
        "SELECT chapter_idx, title FROM events WHERE book_slug = ? AND chapter_idx BETWEEN ? AND ? "
        "ORDER BY chapter_idx LIMIT 30",
        (slug, v["start_chapter_idx"], v["end_chapter_idx"]),
    ).fetchall()
    ev_count = conn.execute(
        "SELECT COUNT(*) AS n FROM evidence WHERE book_slug = ? AND chapter_idx BETWEEN ? AND ?",
        (slug, v["start_chapter_idx"], v["end_chapter_idx"]),
    ).fetchone()["n"]
    return {
        "idx": v["idx"],
        "title": v["title"],
        "lo": v["start_chapter_idx"],
        "hi": v["end_chapter_idx"],
        "chapters": [dict(c) for c in chapters],
        "chapter_count": len(chapters),
        "summarized": sum(1 for c in chapters if c["summarized"]),
        "entities": [dict(e) for e in ents],
        "foreshadowings": [dict(f) for f in fs],
        "events": [dict(e) for e in events],
        "evidence": ev_count,
    }


def chapter(conn, slug: str, idx: int) -> dict | None:
    c = conn.execute(
        """
        SELECT c.*, v.title AS volume_title, s.text AS summary
        FROM chapters c
        LEFT JOIN volumes v ON v.book_slug = c.book_slug AND v.idx = c.volume_idx
        LEFT JOIN summaries s ON s.book_slug = c.book_slug AND s.scope = 'chapter' AND s.ref_idx = c.idx
        WHERE c.book_slug = ? AND c.idx = ?
        """,
        (slug, idx),
    ).fetchone()
    if c is None:
        return None
    ents = conn.execute(
        """
        SELECT DISTINCT e.name, e.etype, e.importance
        FROM evidence ev JOIN entities e ON e.id = ev.entity_id
        WHERE ev.book_slug = ? AND ev.chapter_idx = ?
        ORDER BY e.importance DESC, e.name
        """,
        (slug, idx),
    ).fetchall()
    events = conn.execute(
        "SELECT title, detail FROM events WHERE book_slug = ? AND chapter_idx = ? ORDER BY id",
        (slug, idx),
    ).fetchall()
    fs = conn.execute(
        "SELECT title, status FROM foreshadowings WHERE book_slug = ? AND planted_chapter_idx = ?",
        (slug, idx),
    ).fetchall()
    quotes = conn.execute(
        "SELECT e.name AS entity, ev.kind, ev.quote FROM evidence ev "
        "LEFT JOIN entities e ON e.id = ev.entity_id "
        "WHERE ev.book_slug = ? AND ev.chapter_idx = ? ORDER BY ev.id LIMIT 30",
        (slug, idx),
    ).fetchall()
    return {
        "idx": c["idx"],
        "title": c["title"],
        "volume": c["volume_idx"],
        "volume_title": c["volume_title"],
        "char_count": c["char_count"],
        "summary": c["summary"],
        "entities": [dict(e) for e in ents],
        "events": [dict(e) for e in events],
        "foreshadowings": [dict(f) for f in fs],
        "evidence": [dict(q) for q in quotes],
    }
