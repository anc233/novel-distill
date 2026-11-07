"""文本工具：不可见字符、换行、文件名、别名归一、相似度、token 估算。"""

from __future__ import annotations

import difflib
import hashlib
import re

try:  # rapidfuzz 的 fuzz.ratio 与 difflib.SequenceMatcher.ratio 口径一致，速度快约 10 倍
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # 未安装时退回标准库，行为不变
    _rf_fuzz = None
from pathlib import Path

_INVISIBLE = dict.fromkeys(
    map(ord, "\ufeff\u200b\u200c\u200d\u2060\u180e\u00ad"), None
)
_CN_PUNCT = "，。！？、；：“”‘’（）《》〈〉【】…—～·"
_FILENAME_MAP = {
    "/": "／", "\\": "＼", ":": "：", "*": "＊", "?": "？",
    '"': "＂", "<": "＜", ">": "＞", "|": "｜", "\n": " ", "\r": " ",
}


def strip_invisible(text: str) -> str:
    return text.translate(_INVISIBLE)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_text(text: str) -> str:
    """入口统一清洗：去掉不可见字符与 BOM，换行归一到 \\n。"""
    text = normalize_newlines(strip_invisible(text))
    return text.replace("\u3000", "　")


def squeeze_blank_lines(text: str, max_blank: int = 1) -> str:
    return re.sub(rf"\n{{{max_blank + 2},}}", "\n" * (max_blank + 1), text)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename(name: str, max_len: int = 80, fallback: str = "未命名") -> str:
    """转成可跨平台的文件名：非法字符换全角，去掉控制字符与结尾点/空格。"""
    s = strip_invisible(normalize_newlines(name or "")).strip()
    out = []
    for ch in s:
        if ch in _FILENAME_MAP:
            out.append(_FILENAME_MAP[ch])
        elif ord(ch) < 32:
            continue
        else:
            out.append(ch)
    s = "".join(out).strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s or fallback


def norm_key(name: str) -> str:
    """别名比对键：小写、去空白与中英文标点。"""
    s = (name or "").lower()
    s = re.sub(r"\s+", "", s)
    s = "".join(ch for ch in s if ch not in _CN_PUNCT and ch not in ",.!?;:\"'()[]{}<>-_/\\|")
    return s


def similarity(a: str, b: str) -> float:
    ka, kb = norm_key(a), norm_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    if _rf_fuzz is not None:
        return _rf_fuzz.ratio(ka, kb) / 100.0
    return difflib.SequenceMatcher(None, ka, kb).ratio()


def estimate_tokens(chars: int, chars_per_token: float = 1.5) -> int:
    return round(chars / chars_per_token)


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(ellipsis))] + ellipsis


def count_chars(text: str) -> int:
    """正文字数：不计空白。"""
    return len(re.sub(r"\s", "", text or ""))
