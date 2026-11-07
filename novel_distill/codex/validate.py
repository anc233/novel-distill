"""抽取结果校验（V1–V15）。

设计原则：
- **errors 阻断入库**：结构错误、证据编造、实体名缺失。
- **warnings 不阻断**：覆盖不全、疑似重复、关系悬空。悬空关系写进 conflicts 等裁决。
- 校验器只读文件，不改任何东西；apply 前必跑。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..store import jsonl
from ..util.frontmatter import parse, strip_chapter_body
from ..util.text import count_chars, norm_key, similarity
from . import protocol

try:  # 可选依赖：装了 jsonschema 就额外按 schema.json 校验一遍（缺失不影响主流程）
    import jsonschema as _jsonschema
except ImportError:
    _jsonschema = None


@dataclass
class Issue:
    code: str
    where: str
    message: str

    def as_dict(self) -> dict:
        return {"code": self.code, "where": self.where, "message": self.message}


@dataclass
class Report:
    batch: str
    book: str
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "batch": self.batch,
            "book": self.book,
            "ok": self.ok,
            "errors": [e.as_dict() for e in self.errors],
            "warnings": [w.as_dict() for w in self.warnings],
            "conflicts": self.conflicts,
            "stats": self.stats,
        }


def _normalize(text: str) -> str:
    """比对用的归一化：去掉所有空白与常见标点差异，只保留可见字符。"""
    return "".join(ch for ch in text if not ch.isspace())


def load_chapter_bodies(book_dir: Path, chapters: list[int]) -> dict[int, str]:
    manifest = json.loads((book_dir / "manifest.json").read_text(encoding="utf-8"))
    wanted = set(chapters)
    out: dict[int, str] = {}
    for ch in manifest["chapters"]:
        idx = int(ch["idx"])
        if idx not in wanted:
            continue
        text = (book_dir / ch["body_path"]).read_text(encoding="utf-8")
        _meta, body = parse(text)
        out[idx] = strip_chapter_body(body)
    return out


def batch_range(book_dir: Path, batch: str) -> list[int]:
    meta_path = book_dir / "packets" / batch / "packet.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return [int(c["idx"]) for c in meta["chapters"]]
    return []


def _existing_names(book_dir: Path) -> list[dict]:
    return jsonl.read_jsonl(jsonl.path_for(book_dir, "entities"))


def load_prior_dialogue(book_dir: Path) -> set[str]:
    """已入库实体中已有「原文对白」的名字集合（含别名，norm_key 归一化）。"""
    path = book_dir / "codex" / "entities.jsonl"
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = rec.get("data") or {}
        dlg = data.get("dialogue") if isinstance(data, dict) else None
        if not dlg:
            continue
        if rec.get("name"):
            out.add(norm_key(rec["name"]))
        for alias in rec.get("aliases") or []:
            out.add(norm_key(alias))
    return out


def validate_result(book_dir: Path, result: dict) -> Report:
    book = str(result.get("book") or "")
    batch = str(result.get("batch") or "")
    rep = Report(batch=batch, book=book)
    expected = batch_range(book_dir, batch)
    chapters = result.get("chapters") or []
    chapter_set = {int(c) for c in chapters if isinstance(c, int)}

    # V1 顶层结构
    for key in ("book", "batch", "chapters", "entities", "summaries"):
        if key not in result:
            rep.errors.append(Issue("V1", key, f"缺少顶层字段 {key}"))
    if not isinstance(result.get("entities"), list) or not isinstance(result.get("summaries"), list):
        rep.errors.append(Issue("V1", "root", "entities/summaries 必须是数组"))
        return rep
    if expected and chapter_set != set(expected):
        rep.errors.append(
            Issue("V2", "chapters", f"结果章节 {sorted(chapter_set)} 与任务包 {expected} 不一致")
        )
    if not chapters:
        rep.errors.append(Issue("V2", "chapters", "chapters 为空"))

    # V17 JSON Schema 形状校验：结果与 protocol.RESULT_SCHEMA 漂移时提醒（不阻断，便于先补 schema）
    if _jsonschema is not None:
        try:
            validator = _jsonschema.Draft202012Validator(protocol.RESULT_SCHEMA)
            for err in list(validator.iter_errors(result))[:8]:
                rep.warnings.append(
                    Issue("V17", "/".join(str(x) for x in err.path) or "root", "schema 不符：" + err.message[:120])
                )
        except Exception as exc:  # noqa: BLE001 - schema 自身写坏时不阻断抽取
            rep.warnings.append(Issue("V17", "schema", f"schema 校验不可用：{exc}"))

    bodies = load_chapter_bodies(book_dir, sorted(chapter_set) or expected)
    prior_dialogue = load_prior_dialogue(book_dir)

    def body_text(idx: int) -> str:
        return bodies.get(idx, "")

    # V4 实体
    by_key: dict[str, dict] = {}
    names_in_result: set[str] = set()
    for i, ent in enumerate(result["entities"]):
        where = f"entities[{i}]"
        if not isinstance(ent, dict):
            rep.errors.append(Issue("V4", where, "实体必须是对象"))
            continue
        etype = ent.get("etype")
        name = (ent.get("name") or "").strip()
        if etype not in protocol.ENTITY_TYPES:
            rep.errors.append(Issue("V4", where, f"未知 etype：{etype}"))
        if not name:
            rep.errors.append(Issue("V4", where, "name 为空"))
            continue
        if len(name) > 40:
            rep.errors.append(Issue("V4", where, f"name 过长：{name}"))
        imp = ent.get("importance", 3)
        if not isinstance(imp, int) or not (1 <= imp <= 5):
            rep.errors.append(Issue("V4", where, f"importance 必须是 1–5 的整数，收到 {imp!r}"))
        if ent.get("status") and ent["status"] not in ("active", "dead", "sealed", "missing", "unknown"):
            rep.errors.append(Issue("V4", where, f"未知 status：{ent['status']}"))
        if etype == "character" and isinstance(imp, int) and imp >= 4:
            data = ent.get("data") or {}
            dlg = data.get("dialogue") if isinstance(data, dict) else None
            if not dlg and norm_key(name) not in prior_dialogue:
                rep.warnings.append(Issue("V14", where, "角色「" + name + "」重要度 " + str(imp) + " ≥4 但缺 data.dialogue 原文对白"))
            else:
                for d in (dlg if isinstance(dlg, list) else [dlg]):
                    s = str(d)
                    m = re.match(r"^\s*第\s*(\d+)\s*章\s*[：:]\s*", s)
                    if m:
                        cited = int(m.group(1))
                        quote = s[m.end():]
                    else:
                        cited = 0
                        quote = s.split("：", 1)[1] if "：" in s else s
                    quote = quote.strip().strip("「」“”\"'")
                    qn = _normalize(quote)
                    if len(qn) < 4:
                        continue
                    if cited:
                        ok_dlg = qn in _normalize(load_chapter_bodies(book_dir, [cited]).get(cited, ""))
                    else:
                        ok_dlg = any(qn in _normalize(body_text(c)) for c in chapter_set)
                    if not ok_dlg:
                        rep.warnings.append(Issue("V15", where, "角色「" + name + "」对白未在原文中逐字出现：" + s[:30]))
        if etype == "character" and isinstance(imp, int) and imp >= 4:
            data = ent.get("data") or {}
            dlg = data.get("dialogue") if isinstance(data, dict) else None
            addr = data.get("address") if isinstance(data, dict) else None
            if dlg and not addr:
                rep.warnings.append(Issue("V16", where, "角色「" + name + "」有对白但缺 data.address 称呼习惯"))
        if etype == "character" and isinstance(imp, int) and imp < protocol.MIN_CARD_IMPORTANCE:
            rep.warnings.append(
                Issue("V13", where, f"角色「{name}」重要度 {imp} < 建卡阈值 {protocol.MIN_CARD_IMPORTANCE}：龙套应只写进 events/摘要")
            )
        key = norm_key(name)
        if key in by_key:
            rep.warnings.append(Issue("V5", where, f"本批重复实体：{name}（后者会覆盖前者）"))
        by_key[key] = ent
        names_in_result.add(key)
        for alias in ent.get("aliases") or []:
            if alias and norm_key(alias) not in by_key:
                by_key[norm_key(alias)] = ent

    existing = _existing_names(book_dir)
    existing_keys = {norm_key(r.get("name") or ""): r for r in existing if r.get("name")}
    for r in existing:
        for alias in r.get("aliases") or []:
            existing_keys.setdefault(norm_key(alias), r)

    # V6 疑似同一实体（高相似但名字不同且不是别名）→ conflict
    for key, ent in list(by_key.items()):
        if key in existing_keys:
            continue
        if len(key) < 2:
            continue
        for ekey, rec in existing_keys.items():
            if len(ekey) < 2:
                continue
            if similarity(key, ekey) >= 0.9:
                rep.conflicts.append(
                    {
                        "kind": "similar_name",
                        "entity": ent.get("name"),
                        "other": rec.get("name"),
                        "detail": f"新实体「{ent.get('name')}」与既有「{rec.get('name')}」相似度≥0.9，需确认是否同一人",
                    }
                )
                break

    # V7 关系端点
    for i, rel in enumerate(result.get("relations") or []):
        where = f"relations[{i}]"
        src = norm_key((rel.get("src") or "").strip())
        dst = norm_key((rel.get("dst") or "").strip())
        if not src or not dst:
            rep.errors.append(Issue("V7", where, "src/dst 不能为空"))
            continue
        missing = []
        for side, key in (("src", src), ("dst", dst)):
            if key not in by_key and key not in existing_keys:
                missing.append(side)
        if missing:
            rep.conflicts.append(
                {
                    "kind": "unresolved_relation",
                    "entity": rel.get("src"),
                    "other": rel.get("dst"),
                    "detail": f"关系「{rel.get('src')} —{rel.get('rel')}→ {rel.get('dst')}」的 {','.join(missing)} 尚未建卡",
                }
            )

    # V3 证据：逐字子串校验
    ev_count = 0
    for i, ev in enumerate(result.get("evidence") or []):
        where = f"evidence[{i}]"
        idx = ev.get("chapter")
        quote = (ev.get("quote") or "").strip()
        if not isinstance(idx, int) or idx not in bodies:
            rep.errors.append(Issue("V3", where, f"证据章号 {idx!r} 不在本批"))
            continue
        if len(quote) < 6:
            rep.errors.append(Issue("V3", where, "quote 少于 6 字"))
            continue
        if _normalize(quote) not in _normalize(body_text(idx)):
            rep.errors.append(Issue("V3", where, f"第 {idx} 章找不到原文：{quote[:30]}…"))
            continue
        ev_count += 1
        ent_key = norm_key(ev.get("entity") or "")
        if not ent_key:
            rep.errors.append(Issue("V3", where, "证据缺少 entity"))
        elif ent_key not in by_key and ent_key not in existing_keys:
            rep.warnings.append(Issue("V12", where, f"证据指向未建卡实体：{ev.get('entity')}"))
        kind = ev.get("kind") or ""
        if not kind:
            rep.warnings.append(Issue("V12", where, "证据缺少 kind（性格/口吻/战绩/设定…）"))

    # V8 伏笔
    for i, fs in enumerate(result.get("foreshadowings") or []):
        where = f"foreshadowings[{i}]"
        if not (fs.get("title") or "").strip():
            rep.errors.append(Issue("V8", where, "title 为空"))
        if fs.get("status") not in protocol.FORESHADOW_STATUS:
            rep.errors.append(Issue("V8", where, f"status 必须是 {protocol.FORESHADOW_STATUS}"))
        if fs.get("status") == "paid" and not fs.get("paid_chapter"):
            rep.warnings.append(Issue("V8", where, "已回收但没写 paid_chapter"))

    # V9 事件
    for i, evt in enumerate(result.get("events") or []):
        where = f"events[{i}]"
        if not isinstance(evt.get("chapter"), int) or evt["chapter"] not in bodies:
            rep.errors.append(Issue("V9", where, f"事件章号 {evt.get('chapter')!r} 不在本批"))
        if not (evt.get("title") or "").strip():
            rep.errors.append(Issue("V9", where, "事件缺 title"))

    # V10 摘要 + V11 覆盖
    summarised: set[int] = set()
    for i, sm in enumerate(result.get("summaries") or []):
        where = f"summaries[{i}]"
        scope = sm.get("scope")
        if scope not in protocol.SUMMARY_SCOPES:
            rep.errors.append(Issue("V10", where, f"未知 scope：{scope}"))
            continue
        if scope == "chapter":
            ref = sm.get("ref")
            if not isinstance(ref, int) or ref not in bodies:
                rep.errors.append(Issue("V10", where, f"chapter 摘要 ref={ref!r} 不在本批"))
                continue
            summarised.add(ref)
            n = count_chars(sm.get("text") or "")
            if n < 20:
                rep.warnings.append(Issue("V10", where, f"第 {ref} 章摘要过短（{n} 字）"))
        if not (sm.get("text") or "").strip():
            rep.errors.append(Issue("V10", where, "摘要正文为空"))

    missing = sorted(set(bodies) - summarised)
    if missing:
        rep.warnings.append(Issue("V11", "summaries", f"这些章没有摘要：{missing}"))

    rep.stats = {
        "entities": len(result["entities"]),
        "relations": len(result.get("relations") or []),
        "evidence": ev_count,
        "evidence_total": len(result.get("evidence") or []),
        "foreshadowings": len(result.get("foreshadowings") or []),
        "events": len(result.get("events") or []),
        "summaries": len(result.get("summaries") or []),
        "chapters": len(chapters),
    }
    return rep


def validate_file(book_dir: Path, path: Path) -> Report:
    result = json.loads(path.read_text(encoding="utf-8"))
    return validate_result(book_dir, result)
