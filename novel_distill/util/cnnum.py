"""中文数字解析：支持「一/二/两/零/〇」与「十百千万亿」组合，也接受阿拉伯数字。"""

from __future__ import annotations

DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
    "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
BIG_UNITS = {"万": 10_000, "萬": 10_000, "亿": 100_000_000, "億": 100_000_000}

_FULLWIDTH = {ord(c): str(i) for i, c in enumerate("０１２３４５６７８９")}


def normalize_digits(text: str) -> str:
    """全角数字转半角，去掉空白。"""
    return text.translate(_FULLWIDTH).strip()


def parse_number(text: str) -> int | None:
    """把「一百二十三」/「123」/「二十三」解析为 int；无法解析返回 None。"""
    if text is None:
        return None
    s = normalize_digits(text)
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total = 0
    section = 0
    number = 0
    seen = False
    for ch in s:
        if ch in DIGITS:
            number = DIGITS[ch]
            seen = True
        elif ch in UNITS:
            unit = UNITS[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
            seen = True
        elif ch in BIG_UNITS:
            section += number
            total += section * BIG_UNITS[ch]
            section = 0
            number = 0
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + section + number
