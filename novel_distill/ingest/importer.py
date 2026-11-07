"""导入一本书：复制样本 → 编码归一 → 清洗 → 切章 → 写 manifest / 分章 / 报告。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .. import __version__
from ..config import SCHEMA_VERSION, WORKSPACE
from ..util.ids import slugify
from ..util.log import info
from ..util.text import sha256_bytes
from .clean import clean_text
from .encoding import detect_and_decode
from .splitter import SplitResult, split_text


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def default_slug(title: str, sha: str) -> str:
    return slugify(title) or f"book-{sha[:8]}"


def _chapter_md(book_title: str, slug: str, chapter, volume_title: str) -> str:
    fm = [
        "---",
        "type: chapter",
        f"book: {yaml_str(book_title)}",
        f"book_slug: {slug}",
        f"chapter_idx: {chapter.idx}",
        f"volume_idx: {chapter.volume_idx}",
        f"number: {chapter.number if chapter.number is not None else 'null'}",
        f"title: {yaml_str(chapter.title)}",
        f"raw_heading: {yaml_str(chapter.raw_heading)}",
        f"volume: {yaml_str(volume_title)}",
        f"char_count: {chapter.char_count}",
        "---",
        "",
        f"# {chapter.heading_text()}",
        "",
    ]
    return "\n".join(fm) + chapter.body.strip("\n") + "\n"


def split_report_md(manifest: dict) -> str:
    stats = manifest["stats"]
    lines = [
        f"# 切章报告 · {manifest['title']}",
        "",
        f"- 生成时间：{manifest['created_at']}",
        f"- 源文件：`{manifest['source']['path']}`",
        f"- 编码：{manifest['source']['encoding']}（BOM={manifest['source']['bom']}，替换字符={manifest['source']['replacement_count']}）",
        f"- sha256：`{manifest['source']['sha256']}`",
        "",
        "## 总体",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 总字数（不计空白） | {stats['total_chars']:,} |",
        f"| 已归属正文字数 | {stats['assigned_chars']:,} |",
        f"| 归属率 | {stats['coverage']:.2%} |",
        f"| 卷数 | {stats['volume_count']} |",
        f"| 章数 | {stats['chapter_count']} |",
        f"| 平均章长 | {stats['avg_chapter_chars']:.0f} |",
        f"| 首章前字数 | {stats['preamble_chars']:,} |",
        f"| 清洗删除行 | {manifest['clean']['removed_lines']:,} |",
        "",
        "## 卷",
        "",
        "| 卷 | 标题 | 章范围 | 章数 | 字数 |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {v['idx']} | {v['title'] or '（无标题）'} | {v['start_chapter_idx']}–{v['end_chapter_idx']} | "
        f"{v['chapter_count']} | {v['char_count']:,} |"
        for v in manifest["volumes"]
    )
    counts = manifest["anomaly_counts"]
    lines += ["", "## 异常", ""]
    if not counts:
        lines.append("无异常。")
    else:
        lines.append("| 类型 | 数量 |")
        lines.append("|---|---|")
        for k, n in counts.items():
            lines.append(f"| {k} | {n} |")
        lines += ["", "### 明细（最多 50 条）", ""]
        for a in manifest["anomalies"][:50]:
            lines.append(f"- {a['kind']} 第 {a['chapter_idx']} 章：{a['detail']}")
        if len(manifest["anomalies"]) > 50:
            lines.append(f"- …另有 {len(manifest['anomalies']) - 50} 条，见 manifest.json")
    return "\n".join(lines) + "\n"


def add_book(
    src: str | Path,
    slug: str | None = None,
    title: str | None = None,
    author: str = "",
    workdir: str | Path | None = None,
    write_chapters: bool = True,
    overwrite: bool = False,
    max_heading_len: int = 80,
) -> dict:
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"找不到源文件：{src}")
    data = src.read_bytes()
    sha = sha256_bytes(data)
    dec = detect_and_decode(data)
    clean = clean_text(dec.text)
    sp: SplitResult = split_text(clean.text, max_heading_len=max_heading_len)

    title = (title or src.stem).strip()
    slug = slug or default_slug(title, sha)
    book_dir = Path(workdir or WORKSPACE) / slug
    if book_dir.exists() and not overwrite:
        info(f"[i] 目录已存在，覆盖重建：{book_dir}")
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "chapters").mkdir(exist_ok=True)
    (book_dir / "codex").mkdir(exist_ok=True)
    (book_dir / "results").mkdir(exist_ok=True)

    source_copy = book_dir / "source.txt"
    if (not source_copy.exists()) or overwrite:
        shutil.copyfile(src, source_copy)

    vol_titles = {v.idx: v.title for v in sp.volumes}
    if write_chapters:
        for ch in sp.chapters:
            vdir = book_dir / "chapters" / f"v{ch.volume_idx:02d}"
            vdir.mkdir(parents=True, exist_ok=True)
            rel = Path("chapters") / f"v{ch.volume_idx:02d}" / f"c{ch.idx:04d}.md"
            (book_dir / rel).write_text(
                _chapter_md(title, slug, ch, vol_titles.get(ch.volume_idx, "")), encoding="utf-8"
            )

    total = sp.total_chars
    assigned = sp.assigned_chars
    manifest = {
        "schema": SCHEMA_VERSION,
        "tool_version": __version__,
        "slug": slug,
        "title": title,
        "author": author,
        "source": {
            "path": str(src.resolve()),
            "copy": str(source_copy.relative_to(book_dir)),
            "bytes": len(data),
            "sha256": sha,
            "encoding": dec.encoding,
            "bom": dec.bom,
            "replacement_count": dec.replacement_count,
        },
        "clean": clean.as_dict(),
        "stats": {
            "total_chars": total,
            "assigned_chars": assigned,
            "coverage": round(sp.coverage, 6),
            "preamble_chars": sp.preamble_chars,
            "volume_count": len(sp.volumes),
            "chapter_count": len(sp.chapters),
            "avg_chapter_chars": round(assigned / len(sp.chapters), 1) if sp.chapters else 0,
        },
        "volumes": [
            {
                "idx": v.idx,
                "number": v.number,
                "title": v.title,
                "raw_heading": v.raw_heading,
                "start_chapter_idx": v.start_chapter_idx,
                "end_chapter_idx": v.end_chapter_idx,
                "chapter_count": sum(1 for c in sp.chapters if c.volume_idx == v.idx),
                "char_count": v.char_count,
                "implicit": v.implicit,
            }
            for v in sp.volumes
        ],
        "chapters": [
            {
                "idx": c.idx,
                "volume_idx": c.volume_idx,
                "number": c.number,
                "title": c.title,
                "raw_heading": c.raw_heading,
                "char_count": c.char_count,
                "body_path": f"chapters/v{c.volume_idx:02d}/c{c.idx:04d}.md",
            }
            for c in sp.chapters
        ],
        "anomalies": sp.anomalies,
        "anomaly_counts": sp.anomaly_counts(),
        "created_at": _now(),
    }
    (book_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (book_dir / "split-report.md").write_text(split_report_md(manifest), encoding="utf-8")
    manifest["db"] = sync_database(book_dir, manifest, sp)
    return manifest


def sync_database(book_dir: Path, manifest: dict, sp: SplitResult) -> dict:
    """把卷/章（含正文）与切章异常写进 book.db；返回库内统计。"""
    from ..store import db, repo

    conn = db.connect(book_dir / "book.db")
    try:
        repo.ensure_book(
            conn,
            slug=manifest["slug"],
            title=manifest["title"],
            author=manifest.get("author") or "",
            sha256=manifest["source"]["sha256"],
            encoding=manifest["source"]["encoding"],
            total_chars=manifest["stats"]["total_chars"],
        )
        volumes = manifest["volumes"]
        chapters = [
            {
                "idx": c.idx,
                "volume_idx": c.volume_idx,
                "number": c.number,
                "number_raw": c.number_raw,
                "title": c.title,
                "raw_heading": c.raw_heading,
                "char_count": c.char_count,
                "body": c.body,
            }
            for c in sp.chapters
        ]
        repo.replace_structure(conn, manifest["slug"], volumes, chapters)
        repo.add_anomalies(conn, manifest["slug"], sp.anomalies)
        conn.commit()
        return repo.stats(conn, manifest["slug"])
    finally:
        conn.close()


def load_manifest(slug: str, workdir: str | Path | None = None) -> dict:
    path = Path(workdir or WORKSPACE) / slug / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"没有找到 manifest：{path}（先运行 add）")
    return json.loads(path.read_text(encoding="utf-8"))
