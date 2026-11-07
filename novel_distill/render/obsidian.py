"""把数据库里的设定渲染成 Obsidian 笔记（纯 Markdown + frontmatter + 双链，零插件依赖）。

产物结构（vault 内）：
    修仙蒸馏/<书名>/
        00 总览/总览.md、世界规则/<规则>.md、境界/<境界>.md
        01 角色/…  02 怪物/…  03 秘境/…  04 篇章/…
        05 功法/…  06 法宝/…  07 天才地宝/…  08 势力/…  12 丹药/…
        09 故事梗概/卷NN · 标题.md、章节摘要.md
        10 伏笔/伏笔总表.md、<伏笔>.md
        11 续写/续写上下文.md
        99 统计/统计.md
"""

from __future__ import annotations

import contextlib
import json
import posixpath
from pathlib import Path

from ..config import DEFAULT_BATCH_CHAPTERS, VAULT_SUBDIR, resolve_vault
from ..store import db, repo
from ..util.log import warn

TYPE_DIRS = {
    "character": "01 角色",
    "monster": "02 怪物",
    "dungeon": "03 秘境",
    "arc": "04 篇章",
    "technique": "05 功法",
    "artifact": "06 法宝",
    "material": "07 天才地宝",
    "pill": "12 丹药",
    "faction": "08 势力",
    "world_rule": "00 总览/世界规则",
    "realm": "00 总览/境界",
}

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

DATA_LABELS = {
    "personality": "性格",
    "voice": "口吻",
    "dialogue": "原文对白",
    "address": "称呼习惯",
    "motivation": "核心动机",
    "bottom_line": "底线/逆鳞",
    "habits": "习惯",
    "arc": "心理变化",
    "relations": "对他人的态度",
    "secrets": "秘密",
    "power": "实力/底牌",
    "appearance": "外貌",
    "origin": "来历",
    "goal": "目标",
    "conflict": "当前冲突",
    "nature": "性质",
    "history": "历史",
    "strength": "实力",
    "territory": "地盘",
    "location": "位置",
    "structure": "结构",
    "defense": "防卫",
    "danger": "危险",
    "stage": "阶段",
    "stakes": "赌注",
    "grade": "品阶",
    "effect": "效果",
    "cost": "代价",
    "condition": "修炼条件",
    "product": "产出",
    "weakness": "弱点",
    "material": "材质",
    "unknown": "待解之谜",
    "habit": "习性",
    "limit": "限制",
    "rarity": "稀有度",
    "tier": "品阶",
    "rule": "规则",
    "implication": "影响",
    "setup": "起因",
    "theme": "主题",
    "health": "身体状况",
    "achievement": "事迹",
    "reputation": "名声",
    "thought": "心理",
    "experiment": "实验",
    "hint": "暗示",
    "behavior": "行为",
    "background": "背景",
    "profile": "侧写",
    "scene": "场景",
    "setting": "设定",
    "formula": "丹方",
    "recipe": "丹方",
    "ingredients": "药材",
    "pill_grade": "品相",
    "dosage": "用法用量",
}


def yaml_value(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if v is None:
            continue
        lines.append(f"{k}: {yaml_value(v)}")
    lines.append("---")
    return "\n".join(lines)


def _escape_target(rel: str) -> str:
    """标准 Markdown 链接目标：空格与括号要转义，中文保持可读。"""
    return rel.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


class Linker:
    """生成笔记之间的链接。

    默认输出 Obsidian 双链 `[[修仙蒸馏/书名/01 角色/韩立|韩立]]`（Obsidian 会渲染成
    可点链接，并能解析后缀路径）；`plain=True` 时输出标准 Markdown 相对链接
    `[韩立](韩立.md)` / `[墨大夫](../01%20角色/墨大夫.md)`，任何编辑器都能点。
    """

    def __init__(self, book_title: str, *, plain: bool = False) -> None:
        self.book_title = book_title
        self.plain = plain
        # (etype, name) → 实际落盘文件名；重名实体会带类型后缀，链接必须跟着改
        self.fnames: dict[tuple[str, str], str] = {}

    def link(self, etype: str, name: str, *, display: str | None = None, base: str = "") -> str:
        folder = TYPE_DIRS.get(etype, "00 总览")
        fname = self.fnames.get((etype, name), name)
        return self._render(f"{folder}/{fname}.md", display or name, base)

    def file_link(self, rel: str, *, display: str | None = None, base: str = "") -> str:
        target = rel if rel.endswith(".md") else f"{rel}.md"
        return self._render(target, display or Path(target).stem, base)

    def _render(self, rel: str, text: str, base: str) -> str:
        if self.plain:
            return f"[{text}]({_escape_target(posixpath.relpath(rel, base or '.'))})"
        target = f"{VAULT_SUBDIR}/{self.book_title}/{rel.removesuffix('.md')}"
        return f"[[{target}|{text}]]"


def _entity_note(conn, book: str, book_title: str, row, rels: list[dict], link: Linker) -> str:
    eid = row["id"]
    etype = row["etype"]
    name = row["name"]
    data = json.loads(row["data"] or "{}")
    aliases = [a["alias"] for a in conn.execute("SELECT alias FROM aliases WHERE entity_id = ? ORDER BY alias", (eid,))]
    ev = conn.execute(
        "SELECT chapter_idx, kind, quote FROM evidence WHERE book_slug = ? AND entity_id = ? ORDER BY chapter_idx",
        (book, eid),
    ).fetchall()
    apps = conn.execute(
        "SELECT chapter_idx, role FROM appearances WHERE book_slug = ? AND entity_id = ? ORDER BY chapter_idx",
        (book, eid),
    ).fetchall()

    out: list[str] = []
    out.append(
        _frontmatter(
            {
                "type": etype,
                "id": eid,
                "book": book_title,
                "name": name,
                "aliases": aliases,
                "importance": row["importance"],
                "status": row["status"],
                "first_chapter": row["first_chapter_idx"],
                "last_chapter": row["last_chapter_idx"],
                "tags": [TYPE_LABELS.get(etype, etype)] + (data.get("tags") or []),
                "evidence_count": len(ev),
            }
        )
    )
    out.append("")
    out.append(f"# {name}")
    out.append("")
    if aliases:
        out.append(f"> 别名：{'、'.join(aliases)}　·　类型：{TYPE_LABELS.get(etype, etype)}　·　重要度：{row['importance']}/5")
    else:
        out.append(f"> 类型：{TYPE_LABELS.get(etype, etype)}　·　重要度：{row['importance']}/5")
    out.append("")
    if row["summary"]:
        out.append(row["summary"])
        out.append("")

    # 结构化字段：先角色关键三项，再其余
    key_order = ["personality", "voice", "dialogue", "address", "motivation"]
    ordered = [k for k in key_order if k in data] + [k for k in data if k not in key_order]
    if ordered:
        out.append("## 设定")
        out.append("")
        for k in ordered:
            v = data[k]
            if v in (None, "", [], {}):
                continue
            label = DATA_LABELS.get(k, k)
            if isinstance(v, list):
                out.append(f"### {label}")
                out.append("")
                out.extend(f"- {item}" for item in v)
                out.append("")
            elif isinstance(v, dict):
                out.append(f"### {label}")
                out.append("")
                for kk, vv in v.items():
                    out.append(f"- **{kk}**：{vv}")
                out.append("")
            else:
                out.append(f"### {label}")
                out.append("")
                out.append(str(v))
                out.append("")

    if rels:
        out.append("## 关系")
        out.append("")
        for r in rels:
            other = link.link(r["other_type"], r["other_name"], base=TYPE_DIRS.get(etype, "00 总览"))
            note = f"（{r['note']}）" if r["note"] else ""
            if r["src_id"] == eid:
                out.append(f"- {name} —**{r['rel']}**→ {other}{note}")
            else:
                out.append(f"- {other} —**{r['rel']}**→ {name}{note}")
        out.append("")

    if apps:
        out.append("## 出场章节")
        out.append("")
        chap_line = "、".join(f"第 {a['chapter_idx']} 章" for a in apps)
        out.append(chap_line)
        out.append("")

    if ev:
        out.append("## 原文证据")
        out.append("")
        for e in ev[:40]:
            kind = f"（{e['kind']}）" if e["kind"] else ""
            out.append(f"- 第 {e['chapter_idx']} 章{kind}：「{e['quote']}」")
        if len(ev) > 40:
            out.append(f"- …另有 {len(ev) - 40} 条")
        out.append("")
    return "\n".join(out)


def _relations_for(conn, book: str, eid: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.src_id, r.dst_id, r.rel, r.note, e.name AS other_name, e.etype AS other_type
        FROM relations r JOIN entities e ON e.id = CASE WHEN r.src_id = ? THEN r.dst_id ELSE r.src_id END
        WHERE r.book_slug = ? AND (r.src_id = ? OR r.dst_id = ?)
        ORDER BY e.importance DESC, e.name
        """,
        (eid, book, eid, eid),
    ).fetchall()
    return [dict(r) for r in rows]


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if ch in bad else ch for ch in name).strip().strip(".")
    return out or "未命名"


def _read_manifest(path: Path) -> list[str]:
    """读上次渲染清单；缺失或损坏时返回空列表（宁可不清理，也不误删用户笔记）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    files = data.get("generated") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return []
    return [str(x) for x in files if isinstance(x, str) and x and not x.startswith("..")]


def render_book(
    book_dir: str | Path,
    *,
    vault: str | Path | None = None,
    subdir: str = VAULT_SUBDIR,
    clean: bool = False,
    plain_links: bool = False,
) -> dict:
    book_dir = Path(book_dir)
    db_file = book_dir / "book.db"
    if not db_file.exists():
        raise FileNotFoundError(f"没有数据库：{db_file}（先 add 或 rebuild-db）")
    conn = db.connect(db_file)
    try:
        meta = conn.execute("SELECT * FROM books LIMIT 1").fetchone()
        if meta is None:
            raise ValueError("books 表为空，先 add 一本书")
        slug = meta["slug"]
        title = meta["title"] or slug
        root = Path(vault or resolve_vault()) / subdir / _safe(title)
        manifest_path = root / ".rendered.json"
        removed = 0
        if clean and root.exists():
            # 只删上次渲染清单里的文件：用户在同一目录手写的笔记必须保留
            old = _read_manifest(manifest_path)
            if old:
                for rel in old:
                    cand = root / rel
                    if cand.is_file():
                        cand.unlink()
                        removed += 1
                for d in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
                    with contextlib.suppress(OSError):
                        d.rmdir()
            elif any(root.iterdir()):
                warn(f"{root} 没有 .rendered.json，跳过清理以免误删手写笔记；本次渲染会写入清单，下次可安全 --clean")
        root.mkdir(parents=True, exist_ok=True)
        # 链接风格：Obsidian 双链（默认），或标准 Markdown 相对链接（--plain-links）
        link = Linker(title, plain=plain_links)

        written: list[str] = []

        def write_note(path: Path, text: str) -> None:
            path.write_text(text, encoding="utf-8")
            written.append(path.relative_to(root).as_posix())
        stats = repo.stats(conn, slug)

        # 实体
        entities = conn.execute(
            "SELECT * FROM entities WHERE book_slug = ? ORDER BY etype, importance DESC, name", (slug,)
        ).fetchall()
        index_by_type: dict[str, list[str]] = {}
        used_names: dict[str, int] = {}
        for row in entities:
            fname = _safe(row["name"])
            used_names[fname] = used_names.get(fname, 0) + 1
            if used_names[fname] > 1:
                fname = f"{fname}（{TYPE_LABELS.get(row['etype'], row['etype'])}）"
            link.fnames[(row["etype"], row["name"])] = fname
        for row in entities:
            etype = row["etype"]
            folder = root / TYPE_DIRS.get(etype, "00 总览")
            folder.mkdir(parents=True, exist_ok=True)
            fname = link.fnames[(etype, row["name"])]
            rels = _relations_for(conn, slug, row["id"])
            text = _entity_note(conn, slug, title, row, rels, link)
            path = folder / f"{fname}.md"
            write_note(path, text)
            index_by_type.setdefault(etype, []).append(row["name"])

        # 类型索引
        for etype, names in index_by_type.items():
            folder = root / TYPE_DIRS.get(etype, "00 总览")
            label = TYPE_LABELS.get(etype, etype)
            lines = [_frontmatter({"type": "index", "book": title, "category": label}), "", f"# {label}", ""]
            base = TYPE_DIRS.get(etype, "00 总览")
            lines.extend(f"- {link.link(etype, n, base=base)}" for n in names)
            write_note(folder / f"{label}总表.md", "\n".join(lines) + "\n")

        # 故事梗概：按卷归档章节摘要
        chapters = conn.execute(
            "SELECT c.idx, c.volume_idx, c.title, v.title AS vtitle, s.text "
            "FROM chapters c LEFT JOIN volumes v ON v.book_slug=c.book_slug AND v.idx=c.volume_idx "
            "LEFT JOIN summaries s ON s.book_slug=c.book_slug AND s.scope='chapter' AND s.ref_idx=c.idx "
            "WHERE c.book_slug = ? ORDER BY c.idx",
            (slug,),
        ).fetchall()
        by_volume: dict[tuple[int, str], list] = {}
        for c in chapters:
            by_volume.setdefault((c["volume_idx"], c["vtitle"] or f"第{c['volume_idx']}卷"), []).append(c)
        sumdir = root / "09 故事梗概"
        sumdir.mkdir(parents=True, exist_ok=True)
        summarized = 0
        for (vidx, vtitle), rows in by_volume.items():
            rows = [r for r in rows if r["text"]]
            if not rows:
                continue
            summarized += len(rows)
            lines = [
                _frontmatter({"type": "volume_summary", "book": title, "volume": vidx, "title": vtitle}),
                "",
                f"# 第{vidx}卷 {vtitle}",
                "",
                f"> 第 {rows[0]['idx']}–{rows[-1]['idx']} 章",
                "",
            ]
            for r in rows:
                head = f"### 第 {r['idx']} 章 {r['title'] or ''}".rstrip()
                lines.append(head)
                lines.append("")
                lines.append(r["text"] or "（尚未抽取）")
                lines.append("")
            write_note(sumdir / f"卷{vidx:02d} · {_safe(vtitle)}.md", "\n".join(lines))

        # 伏笔
        fs_rows = conn.execute("SELECT * FROM foreshadowings WHERE book_slug = ? ORDER BY status, title", (slug,)).fetchall()
        fsdir = root / "10 伏笔"
        fsdir.mkdir(parents=True, exist_ok=True)
        lines = [_frontmatter({"type": "index", "book": title, "category": "伏笔"}), "", "# 伏笔总表", ""]
        for fs in fs_rows:
            mark = "🟢 已回收" if fs["status"] == "paid" else ("⚪ 已弃" if fs["status"] == "abandoned" else "🔴 未回收")
            lines.append(f"- {mark} **{fs['title']}**（埋于第 {fs['planted_chapter_idx']} 章）")
            if fs["detail"]:
                lines.append(f"  - {fs['detail']}")
        write_note(fsdir / "伏笔总表.md", "\n".join(lines) + "\n")

        # 总览
        overview_dir = root / "00 总览"
        overview_dir.mkdir(parents=True, exist_ok=True)
        ov = [
            _frontmatter({"type": "overview", "book": title, "slug": slug, "author": meta["author"]}),
            "",
            f"# {title}",
            "",
            f"> 作者：{meta['author'] or '未知'}　·　{stats['volumes']} 卷 / {stats['chapters']} 章　·　实体 {stats['entities']}",
            "",
            "## 蒸馏进度",
            "",
            f"- 已抽取章节摘要：{stats['summaries']} / {stats['chapters']} 章"
            + (f"（{stats['summaries'] / stats['chapters'] * 100:.1f}%）" if stats["chapters"] else ""),
            f"- 已入库批次：{stats['batches_applied']}（每批 {DEFAULT_BATCH_CHAPTERS} 章）",
            f"- 原文证据：{stats['evidence']} 条　·　关系：{stats['relations']} 条　·　待裁决冲突：{stats['conflicts_open']}",
            "",
            "## 设定索引",
            "",
        ]
        for etype in ("character", "monster", "dungeon", "arc", "faction", "technique", "artifact", "material", "pill", "world_rule", "realm"):
            names = index_by_type.get(etype, [])
            if not names:
                continue
            label = TYPE_LABELS[etype]
            ov.append(
                f"- **{label}**（{len(names)}）："
                + "、".join(link.link(etype, n, base="00 总览") for n in names[:12])
            )
        ov += ["", "## 卷目", ""]
        for (vidx, vtitle), rows in by_volume.items():
            ov.append(f"- 第{vidx}卷 {vtitle}（第 {rows[0]['idx']}–{rows[-1]['idx']} 章）")
        ov += ["", "## 统计", "", f"详见 {link.file_link('99 统计/统计.md', display='统计', base='00 总览')}"]
        write_note(overview_dir / "总览.md", "\n".join(ov) + "\n")

        # 统计页（与 CLI stats --db 同源，避免两套口径）
        statdir = root / "99 统计"
        statdir.mkdir(parents=True, exist_ok=True)
        from ..stats.report import collect
        from ..stats.report import markdown as stats_markdown

        rep = collect(book_dir)
        write_note(statdir / "统计.md", stats_markdown(rep))

        # 自检报告随渲染自动刷新（用户 2026-11-06 口径）
        from ..store.lint import lint
        from ..store.lint import markdown as lint_markdown

        write_note(root / "99 统计" / "自检报告.md", lint_markdown(lint(book_dir, vault=root)))

        manifest_path.write_text(
            json.dumps({"tool": "novel-distill", "generated": sorted(written)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"vault": str(root), "files": len(written), "written": written[:40], "removed": removed, "stats": stats}
    finally:
        conn.close()
