from novel_distill.util.ids import (
    chapter_id,
    entity_id,
    slugify,
    stable_hash,
    volume_id,
)
from novel_distill.util.text import (
    count_chars,
    estimate_tokens,
    norm_key,
    safe_filename,
    similarity,
    strip_invisible,
)


def test_slugify_is_ascii_only():
    assert slugify("A B/c") == "a-b-c"
    assert slugify("凡人修仙传") == ""


def test_stable_ids():
    assert stable_hash("hanli", 12) == stable_hash("hanli", 12)
    assert len(stable_hash("hanli")) == 8
    assert entity_id("character", "book-a", "韩立") == entity_id("character", "book-a", " 韩立 ")
    assert entity_id("character", "book-a", "韩立") != entity_id("monster", "book-a", "韩立")
    assert entity_id("character", "book-a", "韩立") != entity_id("character", "book-b", "韩立")
    assert entity_id("character", "book-a", "韩立").startswith("char_")
    assert chapter_id("fanshen", 141) != chapter_id("xianni", 141)
    assert chapter_id("fanshen", 1) != chapter_id("fanshen", 2)
    assert chapter_id("fanshen", 141).endswith("c0141")
    assert volume_id("fanshen", 3).endswith("v03")


def test_text_helpers():
    assert count_chars(" 韩 立 \n") == 2
    assert strip_invisible("a\ufeffb\u200bc") == "abc"
    assert norm_key(" 韩立，你好！") == "韩立你好"
    assert similarity("韩立", " 韩立 ") == 1.0
    assert similarity("韩立", "厉飞雨") < 0.4
    assert estimate_tokens(600) == 400
    assert safe_filename('a/b:c*?"<>|') == "a／b：c＊？＂＜＞｜"
    assert safe_filename("   ") == "未命名"
