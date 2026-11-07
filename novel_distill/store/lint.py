"""设定库自检：把「蒸馏到什么程度、哪里缺、哪里会误导续写」一次列清。

检查项（level=error 表示会直接影响续写正确性，warn 表示质量缺口）：
    thin_entity        重要度 ≥4 但证据 <2
    no_dialogue        重要度 ≥4 的角色没有原文对白
    missing_summary    章节没有摘要（只统计前 10 个 + 总数）
    open_conflict      待裁决设定冲突
    unresolved_evidence 证据没有落到实体
    stale_foreshadow   未回收伏笔埋了超过 50 章
    vault_missing      vault 里清单登记的文件缺失
    vault_unrendered   DB 实体数与 vault 卡片数不一致
    broken_link        vault 里的 [[双链]] 指向不存在的笔记（需 obsidiantools）
    orphan_note        没有任何双链进出的笔记（需 obsidiantools）
    anomaly            切章异常（记录在书里，需人工确认）
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import VAULT_SUBDIR, resolve_vault
from ..store import db, vaultcheck

MAX_LINK_PROBLEMS = 10


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in name).strip().strip(".") or "未命名"


def lint(
    book_dir: str | Path,
    *,
    vault: str | Path | None = None,
    stale_after: int = 50,
    vault_links: bool = True,
) -> dict:
    book_dir = Path(book_dir)
    db_file = book_dir / "book.db"
    if not db_file.exists():
        raise FileNotFoundError(f"没有数据库：{db_file}")
    conn = db.connect(db_file)
    problems: list[dict] = []
    try:
        book = conn.execute("SELECT * FROM books LIMIT 1").fetchone()
        if book is None:
            raise ValueError("books 表为空")
        slug = book["slug"]
        title = book["title"] or slug
        latest = conn.execute(
            "SELECT MAX(ref_idx) AS n FROM summaries WHERE book_slug = ? AND scope = 'chapter'", (slug,)
        ).fetchone()["n"] or 0

        def add(level: str, kind: str, detail: str, ref: str = "") -> None:
            problems.append({"level": level, "kind": kind, "ref": ref, "detail": detail})

        thin = conn.execute(
            """
            SELECT e.name, e.importance,
                   (SELECT COUNT(*) FROM evidence v WHERE v.entity_id = e.id AND v.book_slug = e.book_slug) AS ev
            FROM entities e
            WHERE e.book_slug = ? AND e.importance >= 4
              AND (SELECT COUNT(*) FROM evidence v WHERE v.entity_id = e.id AND v.book_slug = e.book_slug) < 2
            ORDER BY e.importance DESC, ev, e.name
            """,
            (slug,),
        ).fetchall()
        for r in thin:
            add("warn", "thin_entity", f'{r["name"]}（重要度 {r["importance"]}）只有 {r["ev"]} 条证据', r["name"])

        chars = conn.execute(
            "SELECT * FROM entities WHERE book_slug = ? AND etype = 'character' AND importance >= 4", (slug,)
        ).fetchall()
        for c in chars:
            data = json.loads(c["data"] or "{}")
            if not data.get("dialogue"):
                add("warn", "no_dialogue", f'{c["name"]}（重要度 {c["importance"]}）没有原文对白', c["name"])

        missing = conn.execute(
            """
            SELECT c.idx FROM chapters c
            LEFT JOIN summaries s ON s.book_slug = c.book_slug AND s.scope = 'chapter' AND s.ref_idx = c.idx
            WHERE c.book_slug = ? AND s.text IS NULL ORDER BY c.idx
            """,
            (slug,),
        ).fetchall()
        if missing:
            head = "、".join(str(m["idx"]) for m in missing[:10])
            more = "…" if len(missing) > 10 else ""
            add("warn", "missing_summary", f"共 {len(missing)} 章没有摘要：第 {head}{more} 章", "")

        conflicts = conn.execute(
            "SELECT kind, entity_id, other, detail FROM conflicts WHERE book_slug = ? AND status = 'open'", (slug,)
        ).fetchall()
        for c in conflicts:
            add("error", "open_conflict", f'[{c["kind"]}] {c["detail"]}', c["entity_id"] or "")

        orphan = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE book_slug = ? AND (entity_id IS NULL OR entity_id = '')", (slug,)
        ).fetchone()["n"]
        if orphan:
            add("warn", "unresolved_evidence", f"{orphan} 条证据没有落到实体卡（多为提及型龙套）", "")

        stale = conn.execute(
            "SELECT title, planted_chapter_idx FROM foreshadowings "
            "WHERE book_slug = ? AND status = 'open' AND planted_chapter_idx <= ? ORDER BY planted_chapter_idx",
            (slug, max(latest - stale_after, 1)),
        ).fetchall()
        for s in stale:
            add("warn", "stale_foreshadow", f'伏笔「{s["title"]}」埋于第 {s["planted_chapter_idx"]} 章，已过 {latest - s["planted_chapter_idx"]} 章未回收', s["title"])

        anomalies = conn.execute(
            "SELECT kind, chapter_idx, detail FROM anomalies WHERE book_slug = ? ORDER BY kind, chapter_idx", (slug,)
        ).fetchall()
        for a in anomalies:
            add("warn", "anomaly", f'[{a["kind"]}] 第 {a["chapter_idx"]} 章：{a["detail"]}', f'ch{a["chapter_idx"]}')

        vault_base = Path(vault or resolve_vault()) / VAULT_SUBDIR
        root = vault_base / _safe(title)
        manifest = root / ".rendered.json"
        if manifest.exists():
            try:
                files = json.loads(manifest.read_text(encoding="utf-8")).get("generated", [])
            except ValueError:
                files = []
            lost = [f for f in files if not (root / f).exists()]
            if lost:
                add("error", "vault_missing", f"{len(lost)} 个清单文件在 vault 中缺失，例如 {lost[0]}", "")
            n_ent = conn.execute(
                "SELECT COUNT(*) AS n FROM entities WHERE book_slug = ?", (slug,)
            ).fetchone()["n"]
            cards = len(list((root).rglob("*.md")))
            if files and cards < n_ent:
                add("warn", "vault_unrendered", f"DB 有 {n_ent} 个实体，vault 只有 {cards} 个 Markdown（可能未重新 render）", "")
        else:
            add("warn", "vault_unrendered", f"{root} 没有 .rendered.json，尚未渲染或版本过旧", "")

        # 只检查本书目录：同一 Obsidian vault 里其他书的笔记不该算进本书的孤立笔记
        if vault_links and root.is_dir():
            vc = vaultcheck.check_vault(root)
            if vc["available"]:
                broken = vc["broken_links"]
                for b in broken[:MAX_LINK_PROBLEMS]:
                    add("warn", "broken_link", f'{b["note"]} 里的 [[{b["target"]}]] 没有对应笔记', b["note"])
                if len(broken) > MAX_LINK_PROBLEMS:
                    add("warn", "broken_link", f"另有 {len(broken) - MAX_LINK_PROBLEMS} 条断链未列出", "")
                orphans = vc["orphan_notes"]
                for name in orphans[:MAX_LINK_PROBLEMS]:
                    add("warn", "orphan_note", f"{name} 没有任何双链进出（在 Obsidian 里进不去）", name)

        counts: dict[str, int] = {}
        for p in problems:
            counts[p["kind"]] = counts.get(p["kind"], 0) + 1
        return {
            "book": title,
            "upto": latest,
            "ok": not any(p["level"] == "error" for p in problems),
            "problems": problems,
            "counts": counts,
        }
    finally:
        conn.close()


def markdown(rep: dict) -> str:
    lines = [
        "---",
        'type: "lint_report"',
        f'book: {json.dumps(rep["book"], ensure_ascii=False)}',
        f'upto_chapter: {rep["upto"]}',
        "---",
        "",
        f'# {rep["book"]} · 设定库自检',
        "",
        f'> 蒸馏到第 {rep["upto"]} 章；共 {len(rep["problems"])} 条问题，'
        + ("存在阻断级问题。" if not rep["ok"] else "无阻断级问题。"),
        "",
        "## 分类计数",
        "",
    ]
    if rep["counts"]:
        for kind, n in sorted(rep["counts"].items()):
            lines.append(f"- {kind}：{n}")
    else:
        lines.append("- （无）")
    lines += ["", "## 明细", ""]
    if rep["problems"]:
        for p in rep["problems"]:
            mark = "⛔" if p["level"] == "error" else "⚠️"
            lines.append(f'- {mark} **{p["kind"]}**：{p["detail"]}')
    else:
        lines.append("- （无）")
    return "\n".join(lines) + "\n"
