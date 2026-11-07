from novel_distill.util.cnnum import normalize_digits, parse_number


def test_arabic():
    assert parse_number("12") == 12
    assert parse_number("０１２") == 12
    assert normalize_digits(" ３ " ) == "3"


def test_chinese():
    assert parse_number("一") == 1
    assert parse_number("十") == 10
    assert parse_number("十一") == 11
    assert parse_number("二十") == 20
    assert parse_number("一百四十一") == 141
    assert parse_number("两百") == 200
    assert parse_number("一千零一") == 1001
    assert parse_number("二千四百五十一") == 2451


def test_invalid_returns_none():
    assert parse_number("第659章") is None
    assert parse_number("ab") is None
    assert parse_number("") is None
    assert parse_number(None) is None
