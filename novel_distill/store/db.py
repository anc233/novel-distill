"""SQLite 连接与 schema 初始化。DB 可随时从 JSONL + 原文重建。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..config import SCHEMA_VERSION

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def connect(db_path: str | Path, *, create: bool = True) -> sqlite3.Connection:
    """打开数据库：开启外键、WAL、行工厂；create=True 时建表并写入 schema_version。"""
    path = Path(db_path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    if create:
        init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["value"]) if row else 0


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        "books", "volumes", "chapters", "entities", "aliases", "relations",
        "appearances", "evidence", "foreshadowings", "events", "summaries",
        "batches", "conflicts", "anomalies", "stat_snapshots",
    ]
    out: dict[str, int] = {}
    for name in names:
        # name 来自上面的硬编码白名单，不接受外部输入
        out[name] = conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"]  # noqa: S608
    return out
