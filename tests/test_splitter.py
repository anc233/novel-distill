from novel_distill.ingest.splitter import split_text

BOOK = """第一卷 七玄门风云

第一章 山边小村

韩立七岁。村子里的人都姓韩，靠种田打猎为生。

第二章 青牛镇

他跟着三叔去了镇上，第一次见到这么多的人。

第三卷 扬名修魔海 第一百四十一章 斗邪派

卷章同行的正文，这里是斗邪派的场景。

第一百四十二章 住手！

又一个章节，标题以感叹号结尾。
"""


def test_basic_structure():
    r = split_text(BOOK)
    assert [v.title for v in r.volumes] == ["七玄门风云", "扬名修魔海"]
    assert [c.number for c in r.chapters] == [1, 2, 141, 142]
    assert r.chapters[0].body.strip().startswith("韩立七岁")
    assert r.chapters[2].body.strip().startswith("卷章同行的正文")
    assert r.chapters[3].title == "住手！"
    assert r.chapters[2].volume_idx == 2
    assert r.volumes[1].chapter_count == 2


def test_coverage_reasonable():
    r = split_text(BOOK)
    assert r.total_chars > 0
    assert r.assigned_chars > 0
    assert 0.3 < r.coverage <= 1.0


def test_anomalies_match_sample():
    r = split_text(BOOK)
    kinds = {a["kind"] for a in r.anomalies}
    assert "duplicate_number" not in kinds
    assert "duplicate_volume_number" not in kinds
    # 样例章号 1,2,141,142：2→141 的跳号必须被如实报告，不能静默
    gaps = [a for a in r.anomalies if a["kind"] == "gap"]
    assert len(gaps) == 1 and "138" in gaps[0]["detail"]


def test_prose_not_treated_as_volume():
    text = '第一卷 试炼\n\n第一章 开始\n\n第一部分，是他的错。\n第二部分，也是。\n'
    r = split_text(text)
    assert len(r.volumes) == 1
    assert len(r.chapters) == 1


def test_duplicate_volume_number_reported():
    text = "第十一卷 真仙降世\n\n第一章 甲\n\n第十一卷 真仙降临\n\n第二章 乙\n"
    r = split_text(text)
    assert [v.title for v in r.volumes] == ["真仙降世", "真仙降临"]
    assert any(a["kind"] == "duplicate_volume_number" for a in r.anomalies)


def test_gap_reported():
    text = "第一章 甲\n\n正文甲。\n\n第三章 丙\n\n正文丙。\n"
    r = split_text(text)
    assert any(a["kind"] == "gap" for a in r.anomalies)
