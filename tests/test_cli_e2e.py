"""CLI 端到端：从原文导入一路跑到渲染 vault，全程只调 cli.main()，不 mock 内部函数。

这些用例守住的是「命令行契约」：子命令名、参数、退出码、--json 载荷形状。
换了实现只要 CLI 契约不变，它们仍然有效。
"""

import json
from pathlib import Path

import pytest

from novel_distill import cli, config
from novel_distill.ingest import importer
from novel_distill.store import rebuild

SAMPLE = """第一卷 七玄门风云

第一章 山边小村

韩立七岁，和父母住在山边小村。村里来了个走方郎中厉飞雨，厉飞雨看了看韩立的根骨，说这孩子能修仙。韩立听得心里发热，暗暗记下。

第二章 青牛镇

两人一起去了青牛镇，见到墨大夫。墨大夫递给他一只神秘小瓶，说这瓶子能催熟灵药。韩立把瓶子揣进怀里，不敢多问。
"""


def _result(quote: str = "韩立七岁，和父母住在山边小村。") -> dict:
    return {
        "schema_version": 1,
        "book": "t",
        "batch": "b0001",
        "chapters": [1, 2],
        "entities": [
            {
                "etype": "character",
                "name": "韩立",
                "aliases": ["二愣子"],
                "importance": 3,
                "summary": "山边小村的少年，被厉飞雨看出有修仙根骨。",
                "data": {
                    "personality": "谨慎、内敛、记恩也记仇",
                    "voice": "话少，自称「我」，对长辈用「您」",
                    "motivation": "想走出小村，改变命数",
                },
            },
            {
                "etype": "character",
                "name": "厉飞雨",
                "importance": 3,
                "summary": "走方郎中，看出韩立的根骨。",
                "data": {"personality": "热络", "voice": "语速快", "motivation": "游历四方"},
            },
            {
                "etype": "character",
                "name": "墨大夫",
                "importance": 3,
                "summary": "青牛镇的郎中，赠予韩立神秘小瓶。",
                "data": {"personality": "深藏不露", "voice": "慢条斯理", "motivation": "不明"},
            },
            {
                "etype": "artifact",
                "name": "神秘小瓶",
                "importance": 4,
                "summary": "墨大夫所赠，据说能催熟灵药。",
            },
        ],
        "relations": [
            {"src": "厉飞雨", "dst": "韩立", "rel": "识出根骨", "chapter": 1},
            {"src": "墨大夫", "dst": "韩立", "rel": "赠瓶", "chapter": 2},
        ],
        "appearances": [{"entity": "韩立", "chapter": 1, "role": "主角"}],
        "evidence": [
            {"entity": "韩立", "chapter": 1, "quote": quote, "kind": "profile"},
            {"entity": "厉飞雨", "chapter": 1, "quote": "村里来了个走方郎中厉飞雨", "kind": "setting"},
            {"entity": "墨大夫", "chapter": 2, "quote": "墨大夫递给他一只神秘小瓶", "kind": "event"},
            {"entity": "神秘小瓶", "chapter": 2, "quote": "说这瓶子能催熟灵药", "kind": "setting"},
        ],
        "foreshadowings": [{"title": "神秘小瓶的来历", "status": "open", "planted_chapter": 2}],
        "events": [{"chapter": 2, "title": "得瓶", "participants": ["韩立", "墨大夫"]}],
        "summaries": [
            {"scope": "chapter", "ref": 1, "text": "韩立在山边小村被走方郎中厉飞雨看出修仙根骨，心中记下此事。"},
            {"scope": "chapter", "ref": 2, "text": "韩立随厉飞雨到青牛镇，墨大夫赠他一只催熟灵药的神秘小瓶。"},
        ],
        "anomalies": [],
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """把 workspace 指到临时目录；三个模块各自按值导入了 WORKSPACE，要一起换。"""
    ws = tmp_path / "workspace"
    monkeypatch.setattr(config, "WORKSPACE", ws)
    monkeypatch.setattr(cli, "WORKSPACE", ws)
    monkeypatch.setattr(importer, "WORKSPACE", ws)
    monkeypatch.setattr(rebuild, "WORKSPACE", ws)
    return ws


def _run(capsys, *argv) -> tuple[int, str]:
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def _json(out: str):
    """命令可能先打进度行；截出最外层的 JSON 值（对象或数组都行）。"""
    text = out.strip()
    start = min(i for i in (text.find("{"), text.find("[")) if i >= 0)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start : end + 1])


def _import_book(env, tmp_path, capsys) -> None:
    src = tmp_path / "sample.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    assert _run(capsys, "init")[0] == 0
    code, out = _run(capsys, "add", src, "--slug", "t", "--title", "测试书", "--author", "某作者", "--json")
    assert code == 0, out
    assert _json(out)["slug"] == "t"


def _pack(env, capsys) -> str:
    code, out = _run(capsys, "pack", "t", "--from", 1, "--count", 2, "--json")
    assert code == 0, out
    batch = _json(out)["batch"]
    assert batch == "b0001"
    return batch


def _write_result(env, batch: str, result: dict) -> None:
    results = env / "t" / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{batch}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def test_pipeline_import_to_render(env, tmp_path, capsys):
    _import_book(env, tmp_path, capsys)

    code, out = _run(capsys, "stats", "t", "--json")
    assert code == 0
    assert _json(out)["chapter_count"] == 2

    batch = _pack(env, capsys)
    _write_result(env, batch, _result())

    code, out = _run(capsys, "validate", "t", batch, "--json")
    rep = _json(out)
    assert code == 0, rep
    assert rep["ok"] is True and rep["errors"] == []

    code, out = _run(capsys, "apply", "t", batch, "--json")
    applied = _json(out)
    assert code == 0, applied
    assert applied["applied"] is True
    assert applied["stats"]["entities"] == 4

    code, out = _run(capsys, "query", "t", "entity", "韩立", "--json")
    assert code == 0
    ent = _json(out)
    assert ent["name"] == "韩立" and ent["etype"] == "character"
    assert ent["aliases"] == ["二愣子"]

    code, out = _run(capsys, "query", "t", "list", "--type", "artifact", "--json")
    assert code == 0
    assert [r["name"] for r in _json(out)] == ["神秘小瓶"]

    vault = tmp_path / "vault"
    code, out = _run(capsys, "render", "t", "--vault", vault, "--json")
    rendered = _json(out)
    assert code == 0, rendered
    assert rendered["files"] > 0
    # written 是相对「vault/修仙蒸馏/书名」目录的路径
    book_root = Path(rendered["vault"])
    assert book_root.is_dir()
    assert all((book_root / p).exists() for p in rendered["written"][:5])

    code, out = _run(capsys, "lint", "t", "--vault", vault, "--json")
    rep = _json(out)
    assert code in (0, 2), rep
    assert rep["upto"] == 2 and rep["book"]

    code, out = _run(capsys, "pack-continue", "t", "--json")
    pkg = _json(out)
    assert code == 0, pkg
    assert pkg["upto"] == 2 and pkg["characters"] >= 3


def test_apply_is_idempotent(env, tmp_path, capsys):
    _import_book(env, tmp_path, capsys)
    batch = _pack(env, capsys)
    _write_result(env, batch, _result())

    first = _json(_run(capsys, "apply", "t", batch, "--json")[1])
    second = _json(_run(capsys, "apply", "t", batch, "--json")[1])
    assert first["applied"] is True and second["applied"] is True
    assert first["stats"]["entities"] == second["stats"]["entities"] == 4
    assert first["stats"]["evidence"] == second["stats"]["evidence"] == 4


def test_validate_rejects_fabricated_quote(env, tmp_path, capsys):
    _import_book(env, tmp_path, capsys)
    batch = _pack(env, capsys)
    _write_result(env, batch, _result(quote="韩立九岁，独自住进了七玄门后山。"))

    code, out = _run(capsys, "validate", "t", batch, "--json")
    rep = _json(out)
    assert code == 2, rep
    assert rep["ok"] is False
    assert [e["code"] for e in rep["errors"]] == ["V3"]

    code, out = _run(capsys, "apply", "t", batch, "--json")
    refused = _json(out)
    assert code == 2, refused
    assert refused["applied"] is False


def test_doctor_json_all_green(env, tmp_path, capsys):
    code, out = _run(capsys, "doctor", "--json")
    payload = _json(out)
    assert code == 0
    assert payload["ok"] is True
    assert all(c["ok"] for c in payload["checks"])
