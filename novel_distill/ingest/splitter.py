"""卷章切分：处理「卷章同行」、中英数字混排、重号/跳号，异常全部记录不静默。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..util.cnnum import parse_number
from ..util.text import count_chars

CN = "0-9０-９一二三四五六七八九十百千万亿零〇两壹贰叁肆伍陆柒捌玖拾佰仟"

_CHAPTER_BODY = rf"第\s*([{CN}]+)\s*[章回节](?:\s+|(?=[、,，.。:：\-—－·]))?(.{{0,60}})$"
_CHAPTER = re.compile("^" + _CHAPTER_BODY)
_CHAPTER_SEARCH = re.compile(_CHAPTER_BODY)
_VOLUME_SEP = re.compile(rf"^第\s*(?P<num>[{CN}]+)\s*[卷部篇集]\s+(?P<rest>.{{0,50}})$")
_VOLUME_PUNCT = re.compile(rf"^第\s*(?P<num>[{CN}]+)\s*[卷部篇集][、,，.。:：\-—－·]\s*(?P<rest>.{{0,50}})$")
_VOLUME_END = re.compile(rf"^第\s*(?P<num>[{CN}]+)\s*[卷部篇集]$")
_VOLUME_LOOSE = re.compile(rf"^第\s*(?P<num>[{CN}]+)\s*[卷部篇集](?P<rest>.{{0,50}})$")
_SPECIAL = re.compile(r"^(?:序章|楔子|序言|尾声|后记|终章)\s*[、,，.。:：\-—－·]?\s*(.{0,40})$")
_EXTRA = re.compile(r"^(?:番外|外传|特别篇|附录)\s*[、,，.。:：\-—－·]?\s*(.{0,40})$")

SHORT_CHAPTER_CHARS = 50
MAX_CHAPTER_CHARS = 8000
_TITLE_END_BAD = "。！？；…"
_VOLUME_END_BAD = "。！？；…，,、"


@dataclass
class Chapter:
    idx: int
    volume_idx: int
    number: int | None
    number_raw: str
    title: str
    raw_heading: str
    line_no: int
    body: str = ""
    char_count: int = 0

    def heading_text(self) -> str:
        if self.number is not None and self.title:
            return f"第{self.number}章 {self.title}"
        if self.number is not None:
            return f"第{self.number}章"
        return self.raw_heading.strip()


@dataclass
class Volume:
    idx: int
    number: int | None
    title: str
    raw_heading: str
    start_chapter_idx: int = 0
    end_chapter_idx: int = 0
    chapter_count: int = 0
    char_count: int = 0
    implicit: bool = False


@dataclass
class SplitResult:
    volumes: list[Volume]
    chapters: list[Chapter]
    anomalies: list[dict] = field(default_factory=list)
    preamble_chars: int = 0
    total_chars: int = 0
    assigned_chars: int = 0

    @property
    def coverage(self) -> float:
        if not self.total_chars:
            return 0.0
        return self.assigned_chars / self.total_chars

    def anomaly_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self.anomalies:
            counts[a["kind"]] = counts.get(a["kind"], 0) + 1
        return dict(sorted(counts.items()))


def _looks_like_prose(rest: str) -> bool:
    if not rest:
        return False
    if rest[-1] in _VOLUME_END_BAD:
        return True
    return "。" in rest or "！" in rest


def _volume_match(s: str, strict: bool):
    patterns = (_VOLUME_SEP, _VOLUME_PUNCT, _VOLUME_END) if strict else (_VOLUME_LOOSE,)
    for rx in patterns:
        m = rx.match(s)
        if m:
            return m
    return None


def _heading(line: str, max_len: int, strict_volume: bool = True):
    """返回 (kind, number, title, raw, extra)；kind ∈ volume/chapter/volume_merged。"""
    s = line.strip()
    if not s or len(s) > max_len:
        return None
    vm = _volume_match(s, strict_volume)
    if vm:
        gd = vm.groupdict()
        number = parse_number(gd.get("num") or "")
        rest = (gd.get("rest") or "").strip()
        if _looks_like_prose(rest):
            return None
        cm = _CHAPTER_SEARCH.search(rest) if rest else None
        if cm and cm.start() > 0:
            return ("volume_merged", number, rest[: cm.start()].strip(), s, rest[cm.start():])
        return ("volume", number, rest, s, "")
    cm = _CHAPTER.match(s)
    if cm:
        title = (cm.group(2) or "").strip()
        return ("chapter", parse_number(cm.group(1)), title, s, cm.group(1))
    for rx, _kind in ((_SPECIAL, "special"), (_EXTRA, "extra")):
        m = rx.match(s)
        if m:
            return ("chapter", None, (m.group(1) or "").strip(), s, "")
    return None


def _build_marks(lines: list[str], max_heading_len: int):
    marks: list[tuple[int, str, int | None, str, str, str]] = []
    for i, line in enumerate(lines):
        h = _heading(line, max_heading_len, strict_volume=True)
        if not h:
            continue
        kind, number, title, raw, extra = h
        if kind == "volume_merged":
            marks.append((i, "volume_merged", number, title, raw, extra))
            continue
        marks.append((i, kind, number, title, raw, ""))
    return marks


def _append_chapter(cm, lines, marks, pos, chapters, cur_vol):
    line_no = marks[pos][0]
    next_line = len(lines)
    for nxt in marks[pos + 1 :]:
        if nxt[0] > line_no:
            next_line = nxt[0]
            break
    title = (cm.group(2) or "").strip()
    body = "\n".join(lines[line_no + 1 : next_line]).strip("\n")
    ch = Chapter(
        idx=len(chapters) + 1,
        volume_idx=cur_vol.idx,
        number=parse_number(cm.group(1)),
        number_raw=cm.group(1),
        title=title,
        raw_heading=marks[pos][4],
        line_no=line_no,
        body=body,
        char_count=count_chars(body),
    )
    chapters.append(ch)
    cur_vol.chapter_count += 1
    cur_vol.char_count += ch.char_count


def split_text(text: str, max_heading_len: int = 80) -> SplitResult:
    lines = text.split("\n")
    marks = _build_marks(lines, max_heading_len)
    loose = False
    if not any(m[1] == "volume" for m in marks):
        marks = _build_marks_loose(lines, max_heading_len)
        loose = True

    result = SplitResult(volumes=[], chapters=[])
    result.total_chars = count_chars(text)
    if not marks:
        result.anomalies.append({"kind": "no_heading", "chapter_idx": 0, "detail": "未识别到任何卷/章标题"})
        return result

    result.preamble_chars = count_chars("\n".join(lines[: marks[0][0]]))
    if result.preamble_chars > 200:
        result.anomalies.append(
            {"kind": "preamble", "chapter_idx": 0, "detail": f"首章前有 {result.preamble_chars} 字（简介或广告）"}
        )

    volumes: list[Volume] = []
    chapters: list[Chapter] = []
    cur_vol: Volume | None = None
    last_vol_merged = False

    for pos, (line_no, kind, number, title, raw, _extra) in enumerate(marks):
        next_line = len(lines)
        for nxt in marks[pos + 1 :]:
            if nxt[0] > line_no:
                next_line = nxt[0]
                break
        if kind in ("volume", "volume_merged"):
            merged = kind == "volume_merged"
            reuse = False
            if cur_vol is not None and number is not None and cur_vol.number == number:
                if merged or cur_vol.chapter_count == 0 or (last_vol_merged and cur_vol.chapter_count <= 1):
                    # 同卷重复出现（正文里每条章标题前都带卷名，或卷标题重复一次）
                    reuse = True
                    if not cur_vol.title:
                        cur_vol.title = title
                else:
                    result.anomalies.append(
                        {
                            "kind": "duplicate_volume_number",
                            "chapter_idx": len(chapters) + 1,
                            "detail": f"卷号 {number} 重复（{cur_vol.title} / {title}）",
                        }
                    )
            if reuse:
                if merged:
                    cm = _CHAPTER_SEARCH.search(raw)
                    if cm:
                        _append_chapter(cm, lines, marks, pos, chapters, cur_vol)
                continue
            cur_vol = Volume(idx=len(volumes) + 1, number=number, title=title, raw_heading=raw)
            volumes.append(cur_vol)
            last_vol_merged = merged
            if merged:
                cm = _CHAPTER_SEARCH.search(raw)
                if cm:
                    _append_chapter(cm, lines, marks, pos, chapters, cur_vol)
            continue
        if cur_vol is None:
            cur_vol = Volume(idx=1, number=None, title="正文", raw_heading="（无卷标题）", implicit=True)
            volumes.append(cur_vol)
        body = "\n".join(lines[line_no + 1 : next_line]).strip("\n")
        ch = Chapter(
            idx=len(chapters) + 1,
            volume_idx=cur_vol.idx,
            number=number,
            number_raw=str(number) if number is not None else "",
            title=title,
            raw_heading=raw,
            line_no=line_no,
            body=body,
            char_count=count_chars(body),
        )
        chapters.append(ch)
        cur_vol.chapter_count += 1
        cur_vol.char_count += ch.char_count
        continue

    for ch in chapters:
        if ch.char_count == 0:
            result.anomalies.append({"kind": "empty_chapter", "chapter_idx": ch.idx, "detail": f"{ch.heading_text()} 无正文"})
        elif ch.char_count < SHORT_CHAPTER_CHARS:
            result.anomalies.append(
                {"kind": "short_chapter", "chapter_idx": ch.idx, "detail": f"{ch.heading_text()} 仅 {ch.char_count} 字"}
            )
        elif ch.char_count > MAX_CHAPTER_CHARS:
            result.anomalies.append(
                {"kind": "long_chapter", "chapter_idx": ch.idx, "detail": f"{ch.heading_text()} 有 {ch.char_count} 字"}
            )

    prev: int | None = None
    for ch in chapters:
        n = ch.number
        if n is None:
            prev = None
            continue
        if prev is not None:
            if n == prev:
                result.anomalies.append({"kind": "duplicate_number", "chapter_idx": ch.idx, "detail": f"章号 {n} 重复"})
            elif n < prev:
                result.anomalies.append(
                    {"kind": "out_of_order", "chapter_idx": ch.idx, "detail": f"章号 {n} 小于上一章 {prev}"}
                )
            elif n > prev + 1:
                result.anomalies.append(
                    {"kind": "gap", "chapter_idx": ch.idx, "detail": f"章号 {prev} → {n}，缺 {n - prev - 1} 章"}
                )
        prev = n

    for vol in volumes:
        owned = [c for c in chapters if c.volume_idx == vol.idx]
        if owned:
            vol.start_chapter_idx = owned[0].idx
            vol.end_chapter_idx = owned[-1].idx
    if loose:
        result.anomalies.append(
            {"kind": "loose_volume_rule", "chapter_idx": 0, "detail": "严格规则未识别到卷标题，已退回宽松规则"}
        )
    result.volumes = volumes
    result.chapters = chapters
    result.assigned_chars = sum(c.char_count for c in chapters)
    if all(v.implicit for v in volumes):
        result.anomalies.append({"kind": "no_volume_heading", "chapter_idx": 0, "detail": "全书无卷标题，已按单卷处理"})
    return result


def _build_marks_loose(lines: list[str], max_heading_len: int):
    marks: list[tuple[int, str, int | None, str, str, str]] = []
    for i, line in enumerate(lines):
        h = _heading(line, max_heading_len, strict_volume=False)
        if not h:
            continue
        kind, number, title, raw, extra = h
        if kind == "volume_merged":
            marks.append((i, "volume_merged", number, title, raw, extra))
            continue
        marks.append((i, kind, number, title, raw, ""))
    return marks
