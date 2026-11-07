
from novel_distill.ingest.importer import add_book
from novel_distill.store import db, jsonl, repo
from novel_distill.store.rebuild import rebuild_book

SAMPLE = """第一卷 七玄门风云

第一章 山边小村

韩立七岁，和父母住在山边小村。厉飞雨是他同村的玩伴。

第二章 青牛镇

两人一起去了青牛镇，见到墨大夫，得到一只神秘小瓶。
"""


def _make_book(tmp_path, slug="t"):
    src = tmp_path / "sample.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    return add_book(src, slug=slug, title="测试书", author="某作者", workdir=tmp_path)


def test_add_creates_db_with_structure(tmp_path):
    manifest = _make_book(tmp_path)
    conn = db.connect(tmp_path / "t" / "book.db")
    try:
        assert repo.stats(conn, "t")["chapters"] == 2
        assert repo.stats(conn, "t")["volumes"] == 1
        row = conn.execute("SELECT body FROM chapters WHERE book_slug='t' AND idx=1").fetchone()
        assert "韩立七岁" in row["body"]
        hits = repo.search_chapters(conn, "t", '"青牛镇"', 5)
        assert hits and hits[0]["idx"] == 2
        assert manifest["db"]["chapters"] == 2
    finally:
        conn.close()


def test_entity_alias_relation_evidence(tmp_path):
    _make_book(tmp_path)
    book = tmp_path / "t"
    jsonl.upsert_many(
        book,
        "entities",
        [
            {"id": "char_a", "etype": "character", "name": "韩立", "aliases": ["二愣子"], "importance": 5, "summary": "主角"},
            {"id": "char_b", "etype": "character", "name": "厉飞雨", "importance": 3},
            {"id": "art_a", "etype": "artifact", "name": "神秘小瓶", "importance": 4},
        ],
    )
    jsonl.upsert_many(
        book,
        "relations",
        [{"id": "rel_a", "book": "t", "src": "韩立", "dst": "厉飞雨", "rel": "同乡好友", "chapter": 1}],
    )
    jsonl.upsert_many(
        book,
        "evidence",
        [{"book": "t", "entity": "韩立", "chapter": 1, "quote": "韩立七岁，和父母住在山边小村。", "kind": "profile"}],
    )
    jsonl.upsert_many(
        book,
        "foreshadowings",
        [{"id": "fsh_a", "title": "神秘小瓶的来历", "status": "open", "planted_chapter": 2}],
    )
    jsonl.upsert_many(book, "events", [{"id": "evt_a", "chapter": 2, "title": "得瓶", "participants": ["韩立"]}])
    jsonl.upsert_many(book, "summaries", [{"book": "t", "scope": "chapter", "ref": 1, "text": "韩立出场。"}])

    stats = rebuild_book(book)
    assert stats["entities"] == 3
    assert stats["relations"] == 1
    assert stats["evidence"] == 1
    assert stats["foreshadowings"] == {"open": 1}
    assert stats["events"] == 1
    assert stats["summaries"] == 1
    assert stats["unresolved_relations"] == 0

    conn = db.connect(book / "book.db")
    try:
        ent = repo.get_entity(conn, "t", "二愣子")
        assert ent is not None and ent["name"] == "韩立"
        assert ent["aliases"] == ["二愣子"]
        assert len(ent["evidence"]) == 1
        assert repo.resolve_entity(conn, "t", "厉飞雨")["name"] == "厉飞雨"
        assert repo.resolve_entity(conn, "t", "不存在的人") is None
    finally:
        conn.close()


def test_jsonl_upsert_is_idempotent(tmp_path):
    _make_book(tmp_path)
    book = tmp_path / "t"
    rec = {"id": "char_a", "etype": "character", "name": "韩立", "importance": 5}
    assert jsonl.upsert_many(book, "entities", [rec]) == 1
    assert jsonl.upsert_many(book, "entities", [rec]) == 1
    updated = dict(rec, summary="更新后的简介")
    assert jsonl.upsert_many(book, "entities", [updated]) == 1
    rows = jsonl.read_jsonl(jsonl.path_for(book, "entities"))
    assert rows[0]["summary"] == "更新后的简介"


def test_rebuild_matches_incremental(tmp_path):
    _make_book(tmp_path)
    book = tmp_path / "t"
    jsonl.upsert_many(book, "entities", [{"id": "char_a", "etype": "character", "name": "韩立"}])
    rebuild_book(book)

    conn = db.connect(book / "book.db")
    first = repo.stats(conn, "t")
    conn.close()

    rebuild_book(book)
    conn = db.connect(book / "book.db")
    second = repo.stats(conn, "t")
    conn.close()
    assert first == second

    # 关系目标不存在时必须记成 unresolved，而不是静默丢弃
    jsonl.upsert_many(book, "relations", [{"id": "rel_x", "book": "t", "src": "韩立", "dst": "还没出现的人", "rel": "师徒"}])
    stats = rebuild_book(book)
    assert stats["unresolved_relations"] == 1
    assert stats["relations"] == 0

def test_upsert_entity_merges_across_batches(tmp_path):
    _make_book(tmp_path)
    book = tmp_path / "t"
    conn = db.connect(book / "book.db")
    try:
        repo.upsert_entity(
            conn, "t",
            {"etype": "character", "name": "韩立", "importance": 3,
             "summary": "主角", "data": {"personality": "谨慎", "voice": "话少"}},
        )
        repo.upsert_entity(
            conn, "t",
            {"etype": "character", "name": "韩立", "importance": 5,
             "data": {"motivation": "出人头地"}, "first_chapter": 1, "last_chapter": 2},
        )
        ent = repo.get_entity(conn, "t", "韩立")
        assert ent["importance"] == 5
        assert ent["summary"] == "主角", "后一批没写摘要时不能抹掉旧摘要"
        assert ent["data"]["personality"] == "谨慎", "旧字段必须保留"
        assert ent["data"]["motivation"] == "出人头地", "新字段必须合入"
        assert ent["first_chapter"] == 1 and ent["last_chapter"] == 2

        repo.apply_spans(
            conn, "t",
            repo.compute_spans(
                appearances=[{"entity": "韩立", "chapter": 5}],
                relations=[{"src": "韩立", "dst": "墨大夫", "rel": "师徒", "chapter": 3}],
            ),
        )
        ent = repo.get_entity(conn, "t", "韩立")
        assert ent["first_chapter"] == 1, "跨度只扩不缩"
        assert ent["last_chapter"] == 5
    finally:
        conn.close()

def test_relation_merge_same_pair_and_rel(tmp_path):
    from novel_distill.store import jsonl

    book_dir = tmp_path / "b"
    first = {"id": "rel_old1", "book": "x", "src": "韩立", "dst": "神秘小瓶", "rel": "持有", "chapter": 12, "note": "第12章藏入兽皮袋"}
    second = {"id": "rel_old2", "book": "x", "src": "韩立", "dst": "神秘小瓶", "rel": "持有", "chapter": 10, "note": ""}
    jsonl.upsert_many(book_dir, "relations", [first])
    assert jsonl.upsert_many(book_dir, "relations", [second]) == 1
    recs = jsonl.read_jsonl(jsonl.path_for(book_dir, "relations"))
    assert len(recs) == 1
    assert recs[0]["chapter"] == 10          # 最早章号
    assert recs[0]["note"] == "第12章藏入兽皮袋"  # 备注取较晚出现的那条
    assert recs[0]["id"] == second["id"]     # 用新格式 ID


def test_renormalize_relations_collapses_old_rows(tmp_path):
    from novel_distill.store import jsonl

    book_dir = tmp_path / "b"
    p = jsonl.path_for(book_dir, "relations")
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"id": "rel_a", "book": "x", "src": "韩立", "dst": "神秘小瓶", "rel": "持有", "chapter": 10, "note": ""},
        {"id": "rel_b", "book": "x", "src": "韩立", "dst": "神秘小瓶", "rel": "持有", "chapter": 15, "note": "第15章" },
        {"id": "rel_c", "book": "x", "src": "韩立", "dst": "七玄门", "rel": "属于", "chapter": 1, "note": ""},
    ]
    p.write_text("\n".join(jsonl.json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    assert jsonl.renormalize_relations(book_dir) == 2
    recs = sorted(jsonl.read_jsonl(p), key=lambda r: r["rel"])
    assert recs[0]["chapter"] == 1 and recs[0]["id"].startswith("rel_")
    assert recs[1]["chapter"] == 10 and recs[1]["note"] == "第15章"
    assert len({r["id"] for r in recs}) == 2
