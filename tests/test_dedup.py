"""章节近重复检测（依赖可选包 datasketch）。"""

import pytest

pytest.importorskip("datasketch")

from novel_distill.ingest.importer import add_book
from novel_distill.store.dedup import find_duplicates, shingles

PARA = "韩立背着药篓走在山路上，脚下的碎石硌得生疼，他想起墨大夫说过的话，心里一阵发紧。"

SAMPLE = f"""第一卷 试验

第一章 甲

{PARA * 6}

第二章 乙

{"厉飞雨在青牛镇的茶馆里等了半个时辰，茶博士续了三回水，他始终盯着门口。" * 6}

第三章 丙

{PARA * 6}
"""


def test_shingles_handles_short_and_empty():
    assert shingles("") == set()
    assert shingles("短") == {"短"}
    assert len(shingles("一二三四五六七", k=3)) == 5


def test_finds_duplicated_chapter(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    add_book(src, slug="t", title="测试书", author="某作者", workdir=tmp_path)

    rep = find_duplicates(tmp_path / "t")

    assert rep["chapters"] == 3
    assert [(p["a"], p["b"]) for p in rep["pairs"]] == [(1, 3)]
    assert rep["pairs"][0]["jaccard"] > 0.95


def test_min_chars_skips_short_chapters(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    add_book(src, slug="t", title="测试书", author="某作者", workdir=tmp_path)

    rep = find_duplicates(tmp_path / "t", min_chars=10_000)
    assert rep["compared"] == 0 and rep["skipped"] == 3 and rep["pairs"] == []


def test_infeasible_threshold_says_how_to_fix(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    add_book(src, slug="t", title="测试书", author="某作者", workdir=tmp_path)

    with pytest.raises(ValueError, match="num_perm"):
        find_duplicates(tmp_path / "t", threshold=0.99)
    # 抬 num_perm 后同一阈值可用
    assert find_duplicates(tmp_path / "t", threshold=0.99, num_perm=512)["pairs"][0]["jaccard"] > 0.95


def test_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_duplicates(tmp_path / "nope")


def test_cli_explains_missing_numpy(monkeypatch, capsys):
    """单文件 exe 没内置 numpy/scipy 时，报错要说清楚该装什么。"""
    from novel_distill import cli
    from novel_distill.store import dedup

    def boom(*_args, **_kwargs):
        raise ImportError("No module named 'numpy'")

    monkeypatch.setattr(dedup, "find_duplicates", boom)
    code = cli.main(["dedup", "t"])
    captured = capsys.readouterr()
    assert code == 3
    assert "numpy" in (captured.out + captured.err)
