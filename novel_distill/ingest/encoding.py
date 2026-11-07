"""编码探测：优先 UTF-8(-BOM)，失败回退 GB18030；不按字节切片，避免切断多字节字符。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0x3000, 0x303F),
    (0xFF00, 0xFFEF),
)


@dataclass
class Decoded:
    text: str
    encoding: str
    bom: bool
    replacement_count: int

    @property
    def ok(self) -> bool:
        return self.replacement_count == 0


def _cjk_ratio(text: str, sample: int = 20000) -> float:
    head = text[:sample]
    if not head:
        return 0.0
    hits = 0
    for ch in head:
        cp = ord(ch)
        for lo, hi in _CJK_RANGES:
            if lo <= cp <= hi:
                hits += 1
                break
    return hits / len(head)


def detect_and_decode(data: bytes) -> Decoded:
    if data.startswith(b"\xef\xbb\xbf"):
        return Decoded(data.decode("utf-8-sig"), "utf-8-sig", True, 0)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return Decoded(data.decode("utf-16"), "utf-16", True, 0)
        except UnicodeDecodeError:
            pass
    try:
        text = data.decode("utf-8")
        if len(text) < 2000 or _cjk_ratio(text) >= 0.02:
            return Decoded(text, "utf-8", False, 0)
    except UnicodeDecodeError:
        pass
    try:
        return Decoded(data.decode("gb18030"), "gb18030", False, 0)
    except UnicodeDecodeError:
        text = data.decode("gb18030", errors="replace")
        return Decoded(text, "gb18030-replace", False, text.count("\ufffd"))


def read_text_file(path: str | Path) -> Decoded:
    return detect_and_decode(Path(path).read_bytes())
