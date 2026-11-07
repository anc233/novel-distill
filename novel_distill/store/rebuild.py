"""从 workspace（manifest + 分章 md + codex/*.jsonl）重建 book.db。

原则：DB 可丢弃；重建结果必须与增量写入一致（rebuild 是自检手段）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import WORKSPACE
from ..util.frontmatter import parse as parse_frontmatter
from ..util.frontmatter import strip_chapter_body
from . import db, jsonl, repo


def _load_chapters(book_path: Path, manifest: dict) -> list[dict]:
    out: list[dict] = []
    for c in manifest.get("chapters") or []:
        rel = c.get("body_path") or f"chapters/v{c['volume_idx']:02d}/c{c['idx']:04d}.md"
        p = book_path / rel
        body = ""
        if p.exists():
            _, raw = parse_frontmatter(p.read_text(encoding="utf-8"))
            body = strip_chapter_body(raw)
        out.append(
            {
                "idx": c["idx"],
                "volume_idx": c["volume_idx"],
                "number": c.get("number"),
                "number_raw": c.get("number_raw") or "",
                "title": c.get("title") or "",
                "raw_heading": c.get("raw_heading") or "",
                "char_count": c.get("char_count") or len(body.replace("\n", "")),
                "body": body,
            }
        )
    return out


def rebuild_book(book_path: str | Path) -> dict:
    book_path = Path(book_path)
    mpath = book_path / "manifest.json"
    if not mpath.exists():
        raise FileNotFoundError(f"没有 manifest：{mpath}")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    slug = manifest["slug"]
    conn = db.connect(book_path / "book.db")
    try:
        repo.ensure_book(
            conn,
            slug=slug,
            title=manifest.get("title") or slug,
            author=manifest.get("author") or "",
            sha256=(manifest.get("source") or {}).get("sha256") or "",
            encoding=(manifest.get("source") or {}).get("encoding") or "",
            total_chars=int((manifest.get("stats") or {}).get("total_chars") or 0),
        )
        volumes = manifest.get("volumes") or []
        chapters = _load_chapters(book_path, manifest)
        vn, cn = repo.replace_structure(conn, slug, volumes, chapters)
        repo.clear_codex(conn, slug)
        repo.add_anomalies(conn, slug, manifest.get("anomalies") or [])

        entities = jsonl.read_jsonl(jsonl.path_for(book_path, "entities"))
        for rec in entities:
            repo.upsert_entity(conn, slug, rec)
        unresolved = 0
        relations = jsonl.read_jsonl(jsonl.path_for(book_path, "relations"))
        for rec in relations:
            status, _ = repo.upsert_relation(conn, slug, rec)
            if status != "ok":
                unresolved += 1
        appearances = jsonl.read_jsonl(jsonl.path_for(book_path, "appearances"))
        for rec in appearances:
            ent = repo.resolve_entity(conn, slug, rec.get("entity") or "")
            if ent is not None:
                repo.add_appearance(conn, slug, ent["id"], rec.get("chapter"), rec.get("role") or "")
        evidence = jsonl.read_jsonl(jsonl.path_for(book_path, "evidence"))
        for rec in evidence:
            repo.add_evidence(conn, slug, rec)
        for rec in jsonl.read_jsonl(jsonl.path_for(book_path, "foreshadowings")):
            repo.upsert_foreshadowing(conn, slug, rec)
        events = jsonl.read_jsonl(jsonl.path_for(book_path, "events"))
        for rec in events:
            repo.upsert_event(conn, slug, rec)
        repo.apply_spans(
            conn,
            slug,
            repo.compute_spans(
                appearances=appearances,
                evidence=evidence,
                relations=relations,
                events=events,
            ),
        )
        for rec in jsonl.read_jsonl(jsonl.path_for(book_path, "summaries")):
            repo.upsert_summary(conn, slug, rec)
        for rec in jsonl.read_jsonl(jsonl.path_for(book_path, "conflicts")):
            repo.upsert_conflict(conn, slug, rec)
        for rec in jsonl.read_jsonl(jsonl.path_for(book_path, "batches")):
            repo.upsert_batch(conn, slug, rec)
        conn.commit()
        stats = repo.stats(conn, slug)
        stats.update(
            {
                "book_dir": str(book_path),
                "db": str(book_path / "book.db"),
                "codex_entities": len(entities),
                "unresolved_relations": unresolved,
                "chapters_with_body": sum(1 for c in chapters if c["body"]),
                "structure": {"volumes": vn, "chapters": cn},
            }
        )
        return stats
    finally:
        conn.close()


def rebuild_all(workspace: str | Path | None = None) -> list[dict]:
    root = Path(workspace or WORKSPACE)
    out: list[dict] = []
    out.extend(rebuild_book(mpath.parent) for mpath in sorted(root.glob("*/manifest.json")))
    return out
