
import pytest

from novel_distill.codex import protocol
from novel_distill.codex.apply import apply_result
from novel_distill.codex.validate import validate_result
from novel_distill.ingest.importer import add_book
from novel_distill.store import db, repo
from novel_distill.tasks.packet import build_packet

TEXT = """第一卷 七玄门风云

第一章 山边小村

韩立七岁，和父母住在山边小村。他从小就向往外面的世界，梦想走出这个巴掌大的村子。

第二章 青牛镇

韩立跟着三叔去了青牛镇，见到墨大夫。墨大夫给了他一只神秘小瓶，说此物不可示人。

第三章 入门

七玄门招收内门弟子。韩立在山路上遇到厉飞雨，两人结伴同行，约定互相照应。
"""


@pytest.fixture()
def book(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(TEXT, encoding="utf-8")
    add_book(src, slug="t", title="测试书", workdir=tmp_path)
    return tmp_path / "t"


def _result(book_slug="t", batch="b0001"):
    res = protocol.empty_result(book_slug, batch, [1, 2, 3])
    res["entities"] = [
        {
            "etype": "character",
            "name": "韩立",
            "aliases": ["二愣子"],
            "importance": 5,
            "summary": "主角",
            "data": {
                "personality": "谨慎、早熟",
                "voice": "话少，自称我",
                "dialogue": ["第1章：他从小就向往外面的世界，梦想走出这个巴掌大的村子。"],
                "motivation": "出人头地",
            },
        },
        {"etype": "character", "name": "墨大夫", "importance": 3},
    ]
    res["relations"] = [{"src": "韩立", "dst": "墨大夫", "rel": "授业", "chapter": 2}]
    res["evidence"] = [
        {"entity": "韩立", "chapter": 1, "quote": "他从小就向往外面的世界", "kind": "性格"},
        {"entity": "墨大夫", "chapter": 2, "quote": "墨大夫给了他一只神秘小瓶", "kind": "情节"},
    ]
    res["foreshadowings"] = [{"title": "神秘小瓶的来历", "status": "open", "planted_chapter": 2}]
    res["events"] = [{"chapter": 3, "title": "七玄门入门", "participants": ["韩立", "厉飞雨"]}]
    res["summaries"] = [
        {"scope": "chapter", "ref": 1, "text": "韩立出身山边小村，家境清苦，却向往外面的世界，为后续离村埋下动机。"},
        {"scope": "chapter", "ref": 2, "text": "三叔带韩立去青牛镇见墨大夫，墨大夫赠予神秘小瓶，成为全书核心金手指的起点。"},
        {"scope": "chapter", "ref": 3, "text": "七玄门招收内门弟子，韩立与厉飞雨结伴上山，二人约定互相照应，友情线开启。"},
    ]
    return res


def test_packet_files(book):
    out = build_packet(book, start=1, count=3)
    assert out["batch"] == "b0001"
    assert out["chapters"] == [1, 2, 3]
    pdir = book / "packets" / "b0001"
    for name in ("PACKET.md", "packet.json", "schema.json", "result.template.json"):
        assert (pdir / name).exists()
    md = (pdir / "PACKET.md").read_text(encoding="utf-8")
    assert "韩立七岁" in md
    assert "apply t b0001" in md


def test_validate_ok(book):
    rep = validate_result(book, _result())
    assert rep.ok, [e.message for e in rep.errors]
    assert rep.stats["evidence"] == 2


def test_validate_rejects_fabricated_quote(book):
    res = _result()
    res["evidence"][0]["quote"] = "韩立天生就是修仙天才"
    rep = validate_result(book, res)
    assert not rep.ok
    assert any(e.code == "V3" for e in rep.errors)


def test_validate_rejects_wrong_chapter_and_bad_etype(book):
    res = _result()
    res["evidence"][1]["chapter"] = 99
    res["entities"][0]["etype"] = "person"
    rep = validate_result(book, res)
    codes = {e.code for e in rep.errors}
    assert {"V3", "V4"} <= codes


def test_validate_flags_unresolved_relation(book):
    res = _result()
    res["relations"].append({"src": "韩立", "dst": "还没登场的人", "rel": "仇敌", "chapter": 3})
    rep = validate_result(book, res)
    assert rep.ok  # 不阻断
    assert any(c["kind"] == "unresolved_relation" for c in rep.conflicts)


def test_validate_flags_missing_summary(book):
    res = _result()
    res["summaries"] = res["summaries"][:2]
    rep = validate_result(book, res)
    assert any(w.code == "V11" for w in rep.warnings)


def test_apply_is_idempotent(book):
    res = _result()
    first = apply_result(book, "b0001", result=res)
    assert first["applied"] is True
    conn = db.connect(book / "book.db")
    try:
        st1 = repo.stats(conn, "t")
    finally:
        conn.close()

    second = apply_result(book, "b0001", result=res)
    assert second["applied"] is True
    conn = db.connect(book / "book.db")
    try:
        st2 = repo.stats(conn, "t")
    finally:
        conn.close()
    for key in ("entities", "relations", "evidence", "foreshadowings", "events", "summaries", "batches_applied"):
        assert st1[key] == st2[key], key
    assert st2["entities"] == 2


def test_rebuild_is_idempotent_after_apply(book):
    from novel_distill.store.rebuild import rebuild_book

    apply_result(book, "b0001", result=_result())
    a = rebuild_book(book)
    b = rebuild_book(book)
    assert a["relations"] == b["relations"] == len(_result()["relations"])
    assert a["entities"] == b["entities"] == 2
    assert a["evidence"] == b["evidence"] == 2


def test_jsonl_counts_match_result(book):
    from novel_distill.store import jsonl

    res = _result()
    apply_result(book, "b0001", result=res)
    assert jsonl.count(book, "entities") == len(res["entities"])
    assert jsonl.count(book, "relations") == len(res["relations"])
    assert jsonl.count(book, "evidence") == len(res["evidence"])
    assert jsonl.count(book, "events") == len(res["events"])
    assert jsonl.count(book, "foreshadowings") == len(res["foreshadowings"])
    assert jsonl.count(book, "summaries") == len(res["summaries"])


def test_apply_blocks_on_validation_error(book):
    res = _result()
    res["evidence"][0]["quote"] = "这句话原文里没有"
    out = apply_result(book, "b0001", result=res)
    assert out["applied"] is False
    assert out["reason"] == "validation_failed"


def test_apply_records_conflicts_and_entity_data(book):
    res = _result()
    res["relations"].append({"src": "韩立", "dst": "不存在的人", "rel": "师徒", "chapter": 1})
    out = apply_result(book, "b0001", result=res)
    assert out["applied"] is True
    assert out["conflicts"] >= 1
    conn = db.connect(book / "book.db")
    try:
        ent = repo.get_entity(conn, "t", "二愣子")
        assert ent["data"]["personality"].startswith("谨慎")
        assert conn.execute("SELECT COUNT(*) FROM conflicts WHERE book_slug='t' AND status='open'").fetchone()[0] >= 1
    finally:
        conn.close()


def test_dialogue_required_for_major_character(book):
    res = _result()
    del res["entities"][0]["data"]["dialogue"]
    rep = validate_result(book, res)
    assert rep.ok
    assert any(w.code == "V14" for w in rep.warnings)


def test_dialogue_must_be_verbatim(book):
    res = _result()
    res["entities"][0]["data"]["dialogue"] = ["第1章：他从小就向往外面的广阔天地。"]
    rep = validate_result(book, res)
    assert rep.ok
    assert any(w.code == "V15" for w in rep.warnings)
    res["entities"][0]["data"]["dialogue"] = ["第1章：他从小就向往外面的世界"]
    rep2 = validate_result(book, res)
    assert not any(w.code == "V15" for w in rep2.warnings)


def test_dialogue_warning_suppressed_when_already_on_file(book):
    res = _result()
    apply_result(book, "b0001", result=res)
    again = _result()
    del again["entities"][0]["data"]["dialogue"]
    rep = validate_result(book, again)
    assert not any(w.code == "V14" for w in rep.warnings)

def test_entity_span_uses_first_mention_not_batch_start(book):
    """新实体只在批内靠后章节出场时，章号应为实际出场章，而不是批次首章。"""
    res = _result()
    res["entities"].append({"etype": "character", "name": "厉飞雨", "importance": 3, "summary": "同村玩伴"})
    rep = apply_result(book, "b0001", result=res)
    assert rep["applied"]
    conn = db.connect(book / "book.db")
    try:
        ent = repo.get_entity(conn, "t", "厉飞雨")
    finally:
        conn.close()
    assert ent is not None
    assert (ent["first_chapter"], ent["last_chapter"]) == (3, 3)
