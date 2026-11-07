"""清洗：去广告行、统一换行、压缩空行；所有删除计数都记进 stats，便于审计。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..util.text import normalize_text, squeeze_blank_lines

NOISE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("url", re.compile(r"https?://|www\.", re.IGNORECASE)),
    ("site", re.compile(r"笔趣阁|顶点小说|69书吧|新笔趣|笔下文学|小说阅读网|书趣阁|零久文学|无错小说")),
    ("vip", re.compile(r"请记住本站|本站域名|首发地址|最新网址|收藏本站|加入书签|投推荐票|求月票|求订阅|求收藏")),
    ("mobile", re.compile(r"手机阅读|手机用户|手机版|m\.|掌上")),
    ("nav", re.compile(r"点击下一页|本章未完|章节目录|返回目录|百度搜索|一秒记住|更新最快|全文阅读|免费阅读|txt下载")),
    ("ad", re.compile(r"广告|推荐一本|新书发布|书友群|QQ群|qq群")),
]

MAX_NOISE_LINE_LEN = 60


@dataclass
class CleanResult:
    text: str
    removed_lines: int = 0
    removed_chars: int = 0
    removed_by_reason: dict[str, int] = field(default_factory=dict)
    kept_lines: int = 0

    def as_dict(self) -> dict:
        return {
            "removed_lines": self.removed_lines,
            "removed_chars": self.removed_chars,
            "removed_by_reason": dict(sorted(self.removed_by_reason.items())),
            "kept_lines": self.kept_lines,
        }


def _noise_reason(line: str) -> str | None:
    for reason, pat in NOISE_PATTERNS:
        if pat.search(line):
            return reason
    return None


def clean_text(raw: str) -> CleanResult:
    text = normalize_text(raw)
    out: list[str] = []
    result = CleanResult(text="")
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        reason = _noise_reason(stripped) if len(stripped) <= MAX_NOISE_LINE_LEN else None
        if reason:
            result.removed_lines += 1
            result.removed_chars += len(stripped)
            result.removed_by_reason[reason] = result.removed_by_reason.get(reason, 0) + 1
            continue
        out.append(line.rstrip())
        result.kept_lines += 1
    result.text = squeeze_blank_lines("\n".join(out)).strip("\n") + "\n"
    return result


def paragraphs(body: str) -> list[str]:
    return [p.strip() for p in body.split("\n") if p.strip()]
