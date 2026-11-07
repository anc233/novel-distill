-- novel_distill 结构定义（SQLite）
-- 约定：所有内容表都可以从 codex/*.jsonl + workspace 章节文件重建；
--       DB 只是可丢弃的查询缓存/索引，唯一事实源是 JSONL 与原文。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    slug            TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    author          TEXT,
    source_sha256   TEXT,
    source_encoding TEXT,
    total_chars     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS volumes (
    book_slug         TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    idx               INTEGER NOT NULL,
    number            INTEGER,
    title             TEXT NOT NULL DEFAULT '',
    raw_heading       TEXT NOT NULL DEFAULT '',
    start_chapter_idx INTEGER NOT NULL DEFAULT 0,
    end_chapter_idx   INTEGER NOT NULL DEFAULT 0,
    chapter_count     INTEGER NOT NULL DEFAULT 0,
    char_count        INTEGER NOT NULL DEFAULT 0,
    implicit          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_slug, idx)
);

CREATE TABLE IF NOT EXISTS chapters (
    book_slug  TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    volume_idx INTEGER NOT NULL,
    number     INTEGER,
    number_raw TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    raw_heading TEXT NOT NULL DEFAULT '',
    char_count INTEGER NOT NULL DEFAULT 0,
    body       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (book_slug, idx)
);

CREATE INDEX IF NOT EXISTS idx_chapters_volume ON chapters (book_slug, volume_idx);

CREATE VIRTUAL TABLE IF NOT EXISTS chapters_fts USING fts5(
    body,
    title,
    content='chapters',
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chapters_ai AFTER INSERT ON chapters BEGIN
    INSERT INTO chapters_fts (rowid, body, title) VALUES (new.rowid, new.body, new.title);
END;
CREATE TRIGGER IF NOT EXISTS chapters_ad AFTER DELETE ON chapters BEGIN
    INSERT INTO chapters_fts (chapters_fts, rowid, body, title) VALUES ('delete', old.rowid, old.body, old.title);
END;
CREATE TRIGGER IF NOT EXISTS chapters_au AFTER UPDATE ON chapters BEGIN
    INSERT INTO chapters_fts (chapters_fts, rowid, body, title) VALUES ('delete', old.rowid, old.body, old.title);
    INSERT INTO chapters_fts (rowid, body, title) VALUES (new.rowid, new.body, new.title);
END;

-- 实体：character/monster/dungeon/arc/technique/artifact/material/pill/faction/world_rule/realm
CREATE TABLE IF NOT EXISTS entities (
    id                TEXT PRIMARY KEY,
    book_slug         TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    etype             TEXT NOT NULL,
    name              TEXT NOT NULL,
    importance        INTEGER NOT NULL DEFAULT 3,
    status            TEXT NOT NULL DEFAULT 'active',
    summary           TEXT NOT NULL DEFAULT '',
    first_chapter_idx INTEGER,
    last_chapter_idx  INTEGER,
    data              TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (book_slug, etype, name)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (book_slug, etype, importance DESC);

CREATE TABLE IF NOT EXISTS aliases (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias     TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (entity_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases (alias);

CREATE TABLE IF NOT EXISTS relations (
    id          TEXT PRIMARY KEY,
    book_slug   TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    src_id      TEXT NOT NULL,
    dst_id      TEXT NOT NULL,
    rel         TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    chapter_idx INTEGER,
    confidence  REAL NOT NULL DEFAULT 1.0,
    data        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_relations_src ON relations (book_slug, src_id);
CREATE INDEX IF NOT EXISTS idx_relations_dst ON relations (book_slug, dst_id);

CREATE TABLE IF NOT EXISTS appearances (
    entity_id   TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    book_slug   TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    chapter_idx INTEGER NOT NULL,
    role        TEXT NOT NULL DEFAULT '',
    weight      REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (entity_id, chapter_idx)
);

CREATE INDEX IF NOT EXISTS idx_appearances_chapter ON appearances (book_slug, chapter_idx);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_slug   TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    entity_id   TEXT NOT NULL DEFAULT '',
    chapter_idx INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT '',
    quote       TEXT NOT NULL,
    batch       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (book_slug, entity_id, chapter_idx, quote)
);

CREATE INDEX IF NOT EXISTS idx_evidence_entity ON evidence (book_slug, entity_id);

CREATE TABLE IF NOT EXISTS foreshadowings (
    id                 TEXT PRIMARY KEY,
    book_slug          TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open',
    planted_chapter_idx INTEGER,
    paid_chapter_idx   INTEGER,
    detail             TEXT NOT NULL DEFAULT '',
    data               TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_foreshadow_status ON foreshadowings (book_slug, status);

CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    book_slug    TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    chapter_idx  INTEGER,
    title        TEXT NOT NULL,
    participants TEXT NOT NULL DEFAULT '[]',
    detail       TEXT NOT NULL DEFAULT '',
    importance   INTEGER NOT NULL DEFAULT 3,
    data         TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_chapter ON events (book_slug, chapter_idx);

CREATE TABLE IF NOT EXISTS summaries (
    book_slug  TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    scope      TEXT NOT NULL,
    ref_idx    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    batch      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (book_slug, scope, ref_idx)
);

CREATE TABLE IF NOT EXISTS batches (
    id                TEXT PRIMARY KEY,
    book_slug         TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    start_chapter_idx INTEGER NOT NULL,
    end_chapter_idx   INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    packet_path       TEXT NOT NULL DEFAULT '',
    result_path       TEXT NOT NULL DEFAULT '',
    tokens_est        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    applied_at        TEXT,
    error             TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_batches_book ON batches (book_slug, status, start_chapter_idx);

CREATE TABLE IF NOT EXISTS conflicts (
    id         TEXT PRIMARY KEY,
    book_slug  TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    entity_id  TEXT NOT NULL DEFAULT '',
    other      TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_conflicts_open ON conflicts (book_slug, status);

CREATE TABLE IF NOT EXISTS anomalies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_slug   TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    chapter_idx INTEGER NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (book_slug, kind, chapter_idx, detail)
);

CREATE TABLE IF NOT EXISTS stat_snapshots (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    book_slug TEXT NOT NULL REFERENCES books(slug) ON DELETE CASCADE,
    taken_at  TEXT NOT NULL,
    data      TEXT NOT NULL
);
