"""蒸馏统计：把「语料层 + 设定层」的进度汇总成一份可读报告。

用途：
    1. CLI `stats <slug> --db` 直接看；
    2. 渲染时写进 vault 的 `99 统计/统计.md`；
    3. 我（模型）在决定下一批抽哪些章、哪些实体需要补卡时读它。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import DEFAULT_BATCH_CHAPTERS
from ..store import db, repo

TYPE_LABELS = {
    "character": "角色",
    "monster": "怪物",
    "dungeon": "秘境",
    "arc": "篇章",
    "technique": "功法",
    "artifact": "法宝",
    "material": "天才地宝",
    "pill": "丹药",
    "faction": "势力",
    "world_rule": "世界规则",
    "realm": "境界",
}


def collect(book_dir: str | Path) -> dict:
    book_dir = Path(book_dir)
    db_file = book_dir / "book.db"
    if not db_file.exists():
        raise FileNotFoundError(f"没有数据库：{db_file}")
    conn = db.connect(db_file)
    try:
        book = conn.execute("SELECT * FROM books LIMIT 1").fetchone()
        if book is None:
            raise ValueError("books 表为空")
        slug = book["slug"]
        base = repo.stats(conn, slug)

        total_chars = conn.execute(
            "SELECT COALESCE(SUM(char_count), 0) AS n FROM chapters WHERE book_slug = ?", (slug,)
        ).fetchone()["n"]
        summarized = base["summaries"]
        chapters = base["chapters"] or 1

        by_importance = {
            int(r["importance"]): r["n"]
            for r in conn.execute(
                "SELECT importance, COUNT(*) AS n FROM entities WHERE book_slug = ? GROUP BY importance ORDER BY importance DESC",
                (slug,),
            )
        }
        top_entities = [
            dict(r)
            for r in conn.execute(
                """
                SELECT e.name, e.etype, e.importance,
                       (SELECT COUNT(*) FROM evidence v WHERE v.entity_id = e.id) AS ev
                FROM entities e WHERE e.book_slug = ?
                ORDER BY e.importance DESC, ev DESC, e.name LIMIT 15
                """,
                (slug,),
            )
        ]
        thin = [
            dict(r)
            for r in conn.execute(
                """
                SELECT e.name, e.etype, e.importance,
                       (SELECT COUNT(*) FROM evidence v WHERE v.entity_id = e.id) AS ev
                FROM entities e WHERE e.book_slug = ? AND e.importance >= 4
                  AND (SELECT COUNT(*) FROM evidence v WHERE v.entity_id = e.id) < 2
                ORDER BY e.importance DESC, e.name LIMIT 20
                """,
                (slug,),
            )
        ]
        per_volume = [
            dict(r)
            for r in conn.execute(
                """
                SELECT c.volume_idx, COALESCE(v.title, '') AS title,
                       MIN(c.idx) AS lo, MAX(c.idx) AS hi, COUNT(*) AS n,
                       SUM(CASE WHEN s.text IS NOT NULL THEN 1 ELSE 0 END) AS done
                FROM chapters c
                LEFT JOIN volumes v ON v.book_slug = c.book_slug AND v.idx = c.volume_idx
                LEFT JOIN summaries s ON s.book_slug = c.book_slug AND s.scope = 'chapter' AND s.ref_idx = c.idx
                WHERE c.book_slug = ?
                GROUP BY c.volume_idx ORDER BY c.volume_idx
                """,
                (slug,),
            )
        ]
        anomalies = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM anomalies WHERE book_slug = ? GROUP BY kind ORDER BY n DESC", (slug,)
            )
        }
        conflicts = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM conflicts WHERE book_slug = ? AND status = 'open' GROUP BY kind",
                (slug,),
            )
        }
        remaining = max(0, chapters - summarized)
        report = {
            "book": book["title"] or slug,
            "slug": slug,
            "author": book["author"] or "",
            "chapters": base["chapters"],
            "volumes": base["volumes"],
            "total_chars": int(total_chars),
            "avg_chapter_chars": round(total_chars / chapters) if chapters else 0,
            "est_tokens": int(total_chars / 1.5),
            "summarized_chapters": summarized,
            "coverage": round(summarized / chapters, 4) if chapters else 0.0,
            "batches_applied": base["batches_applied"],
            "remaining_chapters": remaining,
            "remaining_batches": (remaining + DEFAULT_BATCH_CHAPTERS - 1) // DEFAULT_BATCH_CHAPTERS,
            "entities": base["entities"],
            "entities_by_type": base["entities_by_type"],
            "by_importance": by_importance,
            "relations": base["relations"],
            "evidence": base["evidence"],
            "events": base["events"],
            "summaries": base["summaries"],
            "foreshadowings": base["foreshadowings"],
            "conflicts_open": base["conflicts_open"],
            "conflicts_by_kind": conflicts,
            "anomalies": base["anomalies"],
            "anomaly_counts": anomalies,
            "top_entities": top_entities,
            "thin_entities": thin,
            "per_volume": per_volume,
        }
        return report
    finally:
        conn.close()


def markdown(rep: dict) -> str:
    lines = [
        "---",
        'type: "stats"',
        f'book: {json.dumps(rep["book"], ensure_ascii=False)}',
        "---",
        "",
        f'# {rep["book"]} · 蒸馏统计',
        "",
        "## 语料",
        "",
        "| 项 | 数值 |",
        "| --- | --- |",
        f'| 卷 / 章 | {rep["volumes"]} / {rep["chapters"]} |',
        f'| 总字数 | {rep["total_chars"]:,} |',
        f'| 平均章长 | {rep["avg_chapter_chars"]:,} 字 |',
        f'| 估算 token | {rep["est_tokens"]:,} |',
        "",
        "## 抽取进度",
        "",
        f'- 已摘要 {rep["summarized_chapters"]} / {rep["chapters"]} 章（{rep["coverage"] * 100:.1f}%）',
        f'- 已入库批次 {rep["batches_applied"]}（每批约 {DEFAULT_BATCH_CHAPTERS} 章）',
        f'- 剩余 {rep["remaining_chapters"]} 章 ≈ {rep["remaining_batches"]} 批',
        "",
        "## 设定规模",
        "",
        "| 项 | 数量 |",
        "| --- | --- |",
        f'| 实体 | {rep["entities"]} |',
        f'| 关系 | {rep["relations"]} |',
        f'| 原文证据 | {rep["evidence"]} |',
        f'| 事件 | {rep["events"]} |',
        f'| 伏笔（未回收） | {rep["foreshadowings"].get("open", 0)} |',
        f'| 待裁决冲突 | {rep["conflicts_open"]} |',
        "",
        "### 按类型",
        "",
    ]
    for k, v in rep["entities_by_type"].items():
        lines.append(f'- {TYPE_LABELS.get(k, k)}：{v}')
    lines += ["", "### 按重要度", ""]
    for k, v in rep["by_importance"].items():
        lines.append(f"- {k}/5：{v}")
    lines += ["", "## 各卷进度", "", "| 卷 | 章范围 | 已摘要 | 覆盖率 |", "| --- | --- | --- | --- |"]
    for v in rep["per_volume"]:
        cov = f"{v['done'] / v['n'] * 100:.0f}%" if v["n"] else "-"
        lines.append(f"| 第{v['volume_idx']}卷 {v['title']} | {v['lo']}–{v['hi']} | {v['done']}/{v['n']} | {cov} |")
    if rep["top_entities"]:
        lines += ["", "## 核心实体（按重要度）", ""]
        for e in rep["top_entities"]:
            lines.append(f'- {e["name"]}（{TYPE_LABELS.get(e["etype"], e["etype"])}，{e["importance"]}/5，证据 {e["ev"]}）')
    if rep["thin_entities"]:
        lines += ["", "## 需要补卡（重要度 ≥4 但证据不足）", ""]
        for e in rep["thin_entities"]:
            lines.append(f'- {e["name"]}（{TYPE_LABELS.get(e["etype"], e["etype"])}，证据 {e["ev"]}）')
    if rep["conflicts_by_kind"] or rep["anomaly_counts"]:
        lines += ["", "## 待处理", ""]
        for k, v in rep["conflicts_by_kind"].items():
            lines.append(f"- 冲突 {k}：{v}")
        for k, v in rep["anomaly_counts"].items():
            lines.append(f"- 原文异常 {k}：{v}")
    return "\n".join(lines) + "\n"
