"""人物口吻卡：把「这个角色会怎么说话、会怎么选」压成一页，供续写时直接取用。

对应 PLAN P7 的「人物口吻卡」交付物；与续写上下文包的区别是：
    续写包 = 当前局势 + 主要人物 + 伏笔（一次一包）
    口吻卡 = 全书角色索引（可随时单独查阅，随蒸馏进度更新）
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import VAULT_SUBDIR, resolve_vault
from ..store import db
from ..util.text import estimate_tokens

FIELDS = [
    ("personality", "性格"),
    ("voice", "口吻"),
    ("dialogue", "原文对白"),
    ("address", "称呼习惯"),
    ("motivation", "动机"),
    ("bottom_line", "底线"),
    ("habits", "习惯"),
    ("power", "实力"),
    ("secrets", "秘密"),
    ("arc", "转变"),
]


def build(
    book_dir: str | Path,
    *,
    min_importance: int = 4,
    limit: int = 30,
    out: str | Path | None = None,
    vault: str | Path | None = None,
) -> dict:
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
        title = book["title"] or slug
        rows = conn.execute(
            "SELECT * FROM entities WHERE book_slug = ? AND etype = 'character' AND importance >= ? "
            "ORDER BY importance DESC, first_chapter_idx, name LIMIT ?",
            (slug, min_importance, limit),
        ).fetchall()

        L: list[str] = [
            "---",
            'type: "voice_cards"',
            f"book: {json.dumps(title, ensure_ascii=False)}",
            f"min_importance: {min_importance}",
            "---",
            "",
            f"# {title} · 人物口吻卡",
            "",
            f"> 收录重要度 ≥ {min_importance} 的角色 {len(rows)} 人；口吻与对白全部来自原文证据，续写时以此为准。",
            "",
        ]
        for row in rows:
            data = json.loads(row["data"] or "{}")
            aliases = [a["alias"] for a in conn.execute("SELECT alias FROM aliases WHERE entity_id = ?", (row["id"],))]
            L.append(f'## {row["name"]}（重要度 {row["importance"]}/5）')
            L.append("")
            if aliases:
                L.append(f'- **别名**：{"、".join(aliases)}')
            if row["summary"]:
                L.append(f'- **一句话**：{row["summary"]}')
            span = ""
            if row["first_chapter_idx"]:
                span = f'第 {row["first_chapter_idx"]}–{row["last_chapter_idx"]} 章'
                L.append(f"- **出场**：{span}")
            for key, label in FIELDS:
                v = data.get(key)
                if not v:
                    continue
                if isinstance(v, list):
                    v = "\n  - ".join(str(x) for x in v)
                    L.append(f"- **{label}**：\n  - {v}")
                else:
                    L.append(f"- **{label}**：{v}")
            rels = conn.execute(
                """
                SELECT r.rel, e.name AS other,
                       CASE WHEN r.src_id = ? THEN 'out' ELSE 'in' END AS dir
                FROM relations r JOIN entities e ON e.id = CASE WHEN r.src_id = ? THEN r.dst_id ELSE r.src_id END
                WHERE r.book_slug = ? AND (r.src_id = ? OR r.dst_id = ?)
                ORDER BY e.importance DESC LIMIT 8
                """,
                (row["id"], row["id"], slug, row["id"], row["id"]),
            ).fetchall()
            if rels:
                parts = [f'{r["other"]}（{r["rel"]}）' if r["dir"] == "out" else f'{r["other"]}→他（{r["rel"]}）' for r in rels]
                L.append(f'- **关系**：{"、".join(parts)}')
            ev = conn.execute(
                "SELECT chapter_idx, quote FROM evidence WHERE book_slug = ? AND entity_id = ? ORDER BY chapter_idx LIMIT 3",
                (slug, row["id"]),
            ).fetchall()
            if ev:
                L.append("- **最早证据**：" + " / ".join(f'第{e["chapter_idx"]}章「{e["quote"]}」' for e in ev))
            L.append("")

        text = "\n".join(L)
        root = Path(vault or resolve_vault()) / VAULT_SUBDIR / _safe(title) / "11 续写"
        path = Path(out) if out else root / "人物口吻卡.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return {
            "book": title,
            "characters": len(rows),
            "path": str(path),
            "chars": len(text),
            "tokens_est": estimate_tokens(len(text)),
        }
    finally:
        conn.close()


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in name).strip().strip(".") or "未命名"
