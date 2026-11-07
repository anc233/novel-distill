"""把通过校验的结果并入事实源（JSONL）与数据库（SQLite），单事务、幂等。

顺序：校验 → 归一化 → 写 codex/*.jsonl（事实源） → 单事务写库 → 记 batches。
任何一步失败都不留半成品：JSONL 是原子重写，库是事务。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..store import db, jsonl, repo
from ..store.db import now_iso
from ..util.ids import entity_id, event_id, foreshadow_id, relation_id, stable_hash
from .validate import Report, validate_result


def result_path(book_dir: Path, batch: str) -> Path:
    return book_dir / "results" / f"{batch}.json"


def normalize(book: str, batch: str, result: dict) -> dict[str, list[dict]]:
    """把结果整理成各表可直接消费的记录；补默认章号与批次号。"""
    chapters = [int(c) for c in result.get("chapters") or []]
    first_ch = min(chapters) if chapters else None
    last_ch = max(chapters) if chapters else None
    # 章号跨度只认「真的被提到」的章：证据/关系两端/事件参与者/显式出场。
    # 否则新实体一律被记成批次首章（绿袍怪人第 28 章出场却记成 24）。
    mentioned: dict[str, set[int]] = {}

    def _touch(name: str, ch) -> None:
        name = (name or "").strip()
        if name and ch:
            mentioned.setdefault(name, set()).add(int(ch))

    for ev in result.get("evidence") or []:
        _touch(ev.get("entity"), ev.get("chapter"))
    for rel in result.get("relations") or []:
        _touch(rel.get("src"), rel.get("chapter") or first_ch)
        _touch(rel.get("dst"), rel.get("chapter") or first_ch)
    for evt in result.get("events") or []:
        for p in evt.get("participants") or []:
            _touch(p, evt.get("chapter"))
    for ap in result.get("appearances") or []:
        _touch(ap.get("entity"), ap.get("chapter"))
    entities = []
    for ent in result.get("entities") or []:
        name = (ent.get("name") or "").strip()
        etype = ent.get("etype") or "concept"
        rec = {
            "id": ent.get("id") or entity_id(etype, book, name),
            "etype": etype,
            "name": name,
            "aliases": [a.strip() for a in (ent.get("aliases") or []) if a and a.strip()],
            "importance": int(ent.get("importance") or 3),
            "status": ent.get("status") or "active",
            "summary": ent.get("summary") or "",
            "first_chapter": ent.get("first_chapter") or (min(mentioned.get(name) or [first_ch]) if first_ch else None),
            "last_chapter": ent.get("last_chapter") or (max(mentioned.get(name) or [last_ch]) if last_ch else None),
            "data": ent.get("data") or {},
            "tags": ent.get("tags") or [],
            "batch": batch,
        }
        entities.append(rec)

    relations = []
    for rel in result.get("relations") or []:
        src = (rel.get("src") or "").strip()
        dst = (rel.get("dst") or "").strip()
        name = (rel.get("rel") or "相关").strip()
        ch = rel.get("chapter") or first_ch
        relations.append(
            {
                "id": relation_id(book, src, dst, name),
                "book": book,
                "src": src,
                "dst": dst,
                "rel": name,
                "chapter": ch,
                "note": rel.get("note") or "",
                "batch": batch,
            }
        )

    evidence = [
        {
            "book": book,
            "entity": (ev.get("entity") or "").strip(),
            "chapter": int(ev.get("chapter")),
            "kind": ev.get("kind") or "",
            "quote": (ev.get("quote") or "").strip(),
            "note": ev.get("note") or "",
            "batch": batch,
        }
        for ev in result.get("evidence") or []
    ]

    foreshadowings = []
    for fs in result.get("foreshadowings") or []:
        title = (fs.get("title") or "").strip()
        foreshadowings.append(
            {
                "id": foreshadow_id(book, title),
                "book": book,
                "title": title,
                "status": fs.get("status") or "open",
                "planted_chapter": fs.get("planted_chapter") or first_ch,
                "paid_chapter": fs.get("paid_chapter"),
                "detail": fs.get("detail") or "",
                "batch": batch,
            }
        )

    events = []
    for evt in result.get("events") or []:
        ch = int(evt.get("chapter"))
        title = (evt.get("title") or "").strip()
        events.append(
            {
                "id": event_id(book, ch, title),
                "book": book,
                "chapter": ch,
                "title": (evt.get("title") or "").strip(),
                "participants": evt.get("participants") or [],
                "detail": evt.get("detail") or "",
                "importance": int(evt.get("importance") or 3),
                "batch": batch,
            }
        )

    summaries = [
        {
            "book": book,
            "scope": sm.get("scope") or "chapter",
            "ref": int(sm.get("ref") or 0),
            "text": sm.get("text") or "",
            "batch": batch,
        }
        for sm in result.get("summaries") or []
    ]

    appearances = [
        {
            "book": book,
            "entity": (ap.get("entity") or "").strip(),
            "chapter": int(ap.get("chapter")),
            "role": ap.get("role") or "",
            "batch": batch,
        }
        for ap in result.get("appearances") or []
    ]

    anomalies = [
        {
            "book": book,
            "kind": a.get("kind") or "unspecified",
            "chapter": int(a.get("chapter") or 0),
            "detail": a.get("detail") or "",
            "batch": batch,
        }
        for a in result.get("anomalies") or []
    ]

    return {
        "entities": entities,
        "relations": relations,
        "evidence": evidence,
        "foreshadowings": foreshadowings,
        "events": events,
        "summaries": summaries,
        "appearances": appearances,
        "anomalies": anomalies,
    }


def apply_result(
    book_dir: Path,
    batch: str,
    *,
    result: dict | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    book = book_dir.name
    if result is None:
        path = result_path(book_dir, batch)
        if not path.exists():
            raise FileNotFoundError(f"没有结果文件：{path}")
        result = json.loads(path.read_text(encoding="utf-8"))
    result["batch"] = batch
    result["book"] = book

    report: Report = validate_result(book_dir, result)
    if not report.ok and not force:
        return {
            "applied": False,
            "batch": batch,
            "reason": "validation_failed",
            "errors": [e.as_dict() for e in report.errors],
            "warnings": [w.as_dict() for w in report.warnings],
        }

    norm = normalize(book, batch, result)
    if dry_run:
        return {
            "applied": False,
            "dry_run": True,
            "batch": batch,
            "counts": {k: len(v) for k, v in norm.items()},
            "warnings": [w.as_dict() for w in report.warnings],
        }

    start, end = min(result["chapters"]), max(result["chapters"])
    batch_rec = {
        "id": batch,
        "start_chapter": start,
        "end_chapter": end,
        "status": "applied",
        "packet_path": f"packets/{batch}",
        "result_path": f"results/{batch}.json",
        "applied_at": now_iso(),
    }

    # 1) 事实源：JSONL（原子重写，幂等）
    counts = {}
    for kind in ("entities", "relations", "evidence", "foreshadowings", "events", "appearances", "summaries", "anomalies"):
        counts[kind] = jsonl.upsert_many(book_dir, kind, norm[kind])
    jsonl.upsert_many(book_dir, "batches", [batch_rec])
    if report.conflicts:
        cfl_recs = []
        for c in report.conflicts:
            cid = "cfl_" + stable_hash(f"{book}|{c.get('kind')}|{c.get('entity')}|{c.get('other')}")
            cfl_recs.append(dict(c, id=cid, book=book, status="open"))
        jsonl.upsert_many(book_dir, "conflicts", cfl_recs)

    # 2) 数据库：单事务
    conn = db.connect(book_dir / "book.db")
    try:
        conn.execute("BEGIN")
        entity_ids: dict[str, str] = {}
        for rec in norm["entities"]:
            eid = repo.upsert_entity(conn, book, rec)
            entity_ids[rec["name"]] = eid
        rel_ok = 0
        for rec in norm["relations"]:
            status, _rid = repo.upsert_relation(conn, book, rec)
            if status == "ok":
                rel_ok += 1
            else:
                repo.upsert_conflict(
                    conn,
                    book,
                    {
                        "kind": "unresolved_relation",
                        "entity": rec["src"],
                        "other": rec["dst"],
                        "detail": f"关系「{rec['src']} —{rec['rel']}→ {rec['dst']}」无法解析端点",
                    },
                )
        for rec in norm["evidence"]:
            repo.add_evidence(conn, book, rec, batch=batch)
        for rec in norm["appearances"]:
            ent = repo.resolve_entity(conn, book, rec["entity"])
            if ent is not None:
                repo.add_appearance(conn, book, ent["id"], rec["chapter"], rec["role"])
        repo.apply_spans(
            conn,
            book,
            repo.compute_spans(
                appearances=norm["appearances"],
                evidence=norm["evidence"],
                relations=norm["relations"],
                events=norm["events"],
            ),
        )
        for rec in norm["foreshadowings"]:
            repo.upsert_foreshadowing(conn, book, rec)
        for rec in norm["events"]:
            repo.upsert_event(conn, book, rec)
        for rec in norm["summaries"]:
            repo.upsert_summary(conn, book, rec)
        for rec in norm["anomalies"]:
            repo.add_anomalies(conn, book, [{"kind": rec["kind"], "chapter_idx": rec["chapter"], "detail": rec["detail"]}])
        for cfl in report.conflicts:
            repo.upsert_conflict(conn, book, cfl)
        repo.upsert_batch(conn, book, batch_rec)
        conn.commit()
        stats = repo.stats(conn, book)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "applied": True,
        "batch": batch,
        "chapters": [min(result["chapters"]), max(result["chapters"])],
        "counts": counts,
        "relations_ok": rel_ok,
        "conflicts": len(report.conflicts),
        "warnings": [w.as_dict() for w in report.warnings],
        "stats": stats,
    }
