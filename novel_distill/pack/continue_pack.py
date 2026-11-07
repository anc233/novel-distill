"""续写上下文包：把「能续写」所需的最小充分信息打包成一份 Markdown。

设计目标（对应 PLAN P7）：
    - 我不需要重读全书就能接手：人物口吻 + 当前局势 + 未回收伏笔 + 最近章节摘要；
    - 明确标注「已蒸馏到第 N 章」，避免我写到抽取范围之外时编造；
    - 同时写出 `11 续写/续写上下文.md`，让用户也能在 Obsidian 里看。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import VAULT_SUBDIR, resolve_vault
from ..store import db
from ..util.text import estimate_tokens

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

CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八"]

CHAR_FIELDS = [
    ("personality", "性格"),
    ("voice", "口吻"),
    ("dialogue", "原文对白"),
    ("address", "称呼习惯"),
    ("motivation", "动机"),
    ("bottom_line", "底线"),
    ("habits", "习惯"),
    ("power", "实力"),
]


def _latest_chapter(conn, slug: str) -> int:
    row = conn.execute(
        "SELECT MAX(ref_idx) AS n FROM summaries WHERE book_slug = ? AND scope = 'chapter'", (slug,)
    ).fetchone()
    return int(row["n"] or 0)


def _char_block(conn, slug: str, row, upto: int) -> list[str]:
    data = json.loads(row["data"] or "{}")
    aliases = [a["alias"] for a in conn.execute("SELECT alias FROM aliases WHERE entity_id = ?", (row["id"],))]
    out = [f'### {row["name"]}（{TYPE_LABELS.get(row["etype"], row["etype"])} · 重要度 {row["importance"]}/5）']
    if aliases:
        out.append(f'别名：{"、".join(aliases)}')
    if row["summary"]:
        out.append(row["summary"])
    for key, label in CHAR_FIELDS:
        v = data.get(key)
        if not v:
            continue
        if isinstance(v, list):
            v = "；".join(str(x) for x in v)
        out.append(f"- **{label}**：{v}")
    rels = conn.execute(
        """
        SELECT r.rel, r.note, e.name AS other, e.etype AS otype,
               CASE WHEN r.src_id = ? THEN 'out' ELSE 'in' END AS dir
        FROM relations r JOIN entities e ON e.id = CASE WHEN r.src_id = ? THEN r.dst_id ELSE r.src_id END
        WHERE r.book_slug = ? AND (r.src_id = ? OR r.dst_id = ?)
        ORDER BY e.importance DESC LIMIT 8
        """,
        (row["id"], row["id"], slug, row["id"], row["id"]),
    ).fetchall()
    if rels:
        parts = []
        for r in rels:
            if r["dir"] == "out":
                parts.append(f'{r["other"]}（{r["rel"]}）')
            else:
                parts.append(f'{r["other"]}→他（{r["rel"]}）')
        out.append(f'- **关系**：{"、".join(parts)}')
    ev = conn.execute(
        "SELECT chapter_idx, quote FROM evidence WHERE book_slug = ? AND entity_id = ? ORDER BY chapter_idx DESC LIMIT 2",
        (slug, row["id"]),
    ).fetchall()
    if ev:
        out.append("- **最近原文**：" + " / ".join(f'第{e["chapter_idx"]}章「{e["quote"]}」' for e in ev))
    out.append("")
    return out


def _style_paragraphs(conn, slug: str, latest: int, chapters: int = 3, per_chapter: int = 2, max_chars: int = 300) -> list[tuple[int, list[str]]]:
    """最近 N 章各取若干段原文：只取长度够的整段，截断到 max_chars，避免包体膨胀。"""
    rows = conn.execute(
        "SELECT idx, body FROM chapters WHERE book_slug = ? AND idx <= ? ORDER BY idx DESC LIMIT ?",
        (slug, latest, chapters),
    ).fetchall()
    out: list[tuple[int, list[str]]] = []
    for row in rows:
        paras = [p.strip() for p in (row["body"] or "").split("\n")]
        paras = [p for p in paras if len(p) >= 40]
        picked = [p[:max_chars] for p in paras[:per_chapter]]
        if picked:
            out.append((row["idx"], picked))
    out.sort(key=lambda x: x[0])
    return out


def build(book_dir: str | Path, *, upto: int | None = None, recent: int = 12, style_sample: bool = True) -> dict:
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
        latest = upto or _latest_chapter(conn, slug)
        if latest <= 0:
            raise ValueError("还没有任何章节摘要，先 pack + apply 至少一批")
        total = conn.execute("SELECT COUNT(*) AS n FROM chapters WHERE book_slug = ?", (slug,)).fetchone()["n"]

        chars = conn.execute(
            "SELECT * FROM entities WHERE book_slug = ? AND etype = 'character' ORDER BY importance DESC, name LIMIT 15",
            (slug,),
        ).fetchall()
        rules = conn.execute(
            "SELECT name, summary, data FROM entities WHERE book_slug = ? AND etype IN ('world_rule','realm') ORDER BY etype, importance DESC",
            (slug,),
        ).fetchall()
        fs = conn.execute(
            "SELECT title, detail, planted_chapter_idx FROM foreshadowings WHERE book_slug = ? AND status = 'open' ORDER BY planted_chapter_idx",
            (slug,),
        ).fetchall()
        recent_sum = conn.execute(
            "SELECT ref_idx, text FROM summaries WHERE book_slug = ? AND scope = 'chapter' AND ref_idx <= ? ORDER BY ref_idx DESC LIMIT ?",
            (slug, latest, recent),
        ).fetchall()
        events = conn.execute(
            "SELECT chapter_idx, title, detail FROM events WHERE book_slug = ? AND chapter_idx <= ? ORDER BY chapter_idx DESC LIMIT 15",
            (slug, latest),
        ).fetchall()
        conflicts = conn.execute(
            "SELECT kind, detail FROM conflicts WHERE book_slug = ? AND status = 'open' LIMIT 20", (slug,)
        ).fetchall()

        L: list[str] = []
        sec = {"n": 0}

        def head(title: str) -> None:
            sec["n"] += 1
            L.extend([f"## {CN_NUM[sec['n']] if sec['n'] <= 8 else sec['n']}、{title}", ""])

        L += [
            "---",
            'type: "continuation_pack"',
            f'book: {json.dumps(title, ensure_ascii=False)}',
            f"upto_chapter: {latest}",
            "---",
            "",
            f"# {title} · 续写上下文包",
            "",
            f"> 已蒸馏：第 1–{latest} 章 / 全书 {total} 章（{latest / max(total, 1) * 100:.1f}%）",
            f"> 用法：只依据本包续写；超出第 {latest} 章的情节必须标注「推测」，不得当作原作事实。",
            "",
        ]
        head("当前局势（最近章节摘要）")
        for s in recent_sum:
            L.append(f"### 第 {s['ref_idx']} 章")
            L.append("")
            L.append(s["text"])
            L.append("")

        head("主要人物（口吻与动机）")
        for row in chars:
            L += _char_block(conn, slug, row, latest)

        if rules:
            head("世界规则与境界体系")
            for r in rules:
                data = json.loads(r["data"] or "{}")
                line = f'- **{r["name"]}**：{r["summary"] or ""}'
                extra = "；".join(f"{k}={v}" for k, v in data.items() if isinstance(v, str))
                if extra:
                    line += f"（{extra}）"
                L.append(line)
            L.append("")

        if fs:
            head("未回收伏笔（续写时应逐步推进，不可无视）")
            for f in fs:
                L.append(f'- **{f["title"]}**（埋于第 {f["planted_chapter_idx"]} 章）{f["detail"] or ""}')
            L.append("")

        if events:
            head("最近事件")
            for e in events:
                L.append(f'- 第 {e["chapter_idx"]} 章 **{e["title"]}**：{e["detail"] or ""}')
            L.append("")

        if conflicts:
            head("待裁决设定冲突（续写前须确认）")
            for c in conflicts:
                L.append(f'- [{c["kind"]}] {c["detail"]}')
            L.append("")

        if style_sample:
            samples = _style_paragraphs(conn, slug, latest)
            if samples:
                head("文风样本（最近章节原文，仅供语感参考，勿抄写）")
                for idx, paras in samples:
                    L.append(f"### 第 {idx} 章")
                    L.append("")
                    for p in paras:
                        L.extend([p, ""])

        text = "\n".join(L)
        outdir = book_dir / "continuation"
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"CONTEXT-{latest:04d}.md"
        path.write_text(text, encoding="utf-8")
        (outdir / "CONTEXT.md").write_text(text, encoding="utf-8")

        vault_path = None
        try:
            root = Path(resolve_vault()) / VAULT_SUBDIR / _safe(title) / "11 续写"
            root.mkdir(parents=True, exist_ok=True)
            (root / "续写上下文.md").write_text(text, encoding="utf-8")
            vault_path = str(root / "续写上下文.md")
        except Exception as exc:  # noqa: BLE001 - vault 不可写不应阻断本地打包
            vault_path = f"(未写入 vault: {exc})"

        return {
            "book": title,
            "upto": latest,
            "chapters_total": total,
            "characters": len(chars),
            "foreshadowings": len(fs),
            "path": str(path),
            "vault_path": vault_path,
            "chars": len(text),
            "tokens_est": estimate_tokens(len(text)),
        }
    finally:
        conn.close()


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in name).strip().strip(".") or "未命名"
