"""任务包生成：把一批章节 + 既有实体名册 + 抽取规则打包成一个自包含目录。

目录形态：
    packets/b0001/
        PACKET.md            给人（模型）读的任务书，内联本批正文
        packet.json          机读版：范围、章节元信息、既有实体
        schema.json          结果 JSON Schema
        result.template.json 空白结果模板
"""

from __future__ import annotations

import json
from pathlib import Path

from ..codex import protocol
from ..config import MAX_CHAPTER_CHARS, MAX_PACKET_CHARS
from ..store import jsonl
from ..util.frontmatter import parse, strip_chapter_body
from ..util.ids import batch_id
from ..util.text import count_chars, estimate_tokens


def load_manifest(book_dir: Path) -> dict:
    path = book_dir / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"没有找到 manifest：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_chapter_body(book_dir: Path, rel_path: str) -> str:
    text = (book_dir / rel_path).read_text(encoding="utf-8")
    _meta, body = parse(text)
    return strip_chapter_body(body).strip()


def chapter_slice(manifest: dict, start: int = 1, count: int = 5) -> list[dict]:
    chapters = manifest["chapters"]
    picked = [c for c in chapters if int(c["idx"]) >= start][:count]
    return picked


def entity_roster(book_dir: Path, limit: int = 120) -> list[dict]:
    """既有实体的精简名册，供抽取时复用名字、避免重复建卡。"""
    rows = jsonl.read_jsonl(jsonl.path_for(book_dir, "entities"))
    rows.sort(key=lambda r: (-int(r.get("importance") or 0), r.get("name") or ""))
    out = []
    out.extend(
        {
            "name": r.get("name"),
            "etype": r.get("etype"),
            "aliases": r.get("aliases") or [],
            "importance": r.get("importance"),
        }
        for r in rows[:limit]
    )
    return out


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…", True


def packet_markdown(
    *,
    manifest: dict,
    batch: str,
    chapters: list[dict],
    bodies: dict[int, str],
    roster: list[dict],
    truncations: dict[int, bool],
) -> str:
    book = manifest["title"]
    slug = manifest["slug"]
    first, last = chapters[0]["idx"], chapters[-1]["idx"]
    lines: list[str] = []
    lines.append(f"# 抽取任务包 · {book} · {batch}")
    lines.append("")
    lines.append(f"- 书：{book}（slug=`{slug}`，作者：{manifest.get('author') or '未知'}）")
    lines.append(f"- 章节范围：第 {first}–{last} 章，共 {len(chapters)} 章")
    lines.append(f"- 结果写入：`workspace/{slug}/results/{batch}.json`（照抄 result.template.json 的骨架）")
    lines.append(f"- 结果必须通过：`python -m novel_distill validate {slug} {batch}`")
    lines.append(f"- 入库：`python -m novel_distill apply {slug} {batch}`")
    lines.append("")
    lines.append("## 抽取要求")
    lines.append("")
    lines.append("1. **只依据本包正文**，不要用你对这本书的既有记忆补全；没读到的不写。")
    lines.append("2. 每条证据 `evidence.quote` 必须是该章正文的**逐字子串**（6–200 字，可跨句但不可改写、不可拼接）。程序会逐条比对，编造会直接让整批校验失败。")
    lines.append("3. 实体名用正文里的正式称呼；别名（道号、绰号、化名）放进 `aliases`，这样后续批次能合并而不是新建重复卡。")
    lines.append("4. 重要度 1–5：" + "；".join(f"{k}={v}" for k, v in protocol.IMPORTANCE_SCALE.items()))
    lines.append("5. 角色卡必须写 `data.personality`（性格）、`data.voice`（口吻）、`data.motivation`（动机），这三项是后续推导角色行为与续写的硬依赖。")
    lines.append("6. 每章至少一条 `summaries`（scope=chapter，ref=章号，text=80–200 字，写清「谁做了什么、结果如何、留下什么钩子」）。")
    lines.append("7. 伏笔：本批新埋的记 `status=open`；本批回收的，把原伏笔标 `status=paid` 并给 `paid_chapter`。")
    lines.append("8. 关系（relations）两端必须能在本批实体或「既有实体名册」里找到；找不到就说明该角色还没建卡，先建卡。")
    lines.append("9. 拿不准的不要丢：写进 `anomalies`（kind=ambiguous_name 等），我后续会裁决。")
    lines.append(f"10. **建卡阈值**：角色重要度 ≥{protocol.MIN_CARD_IMPORTANCE} 才建卡；只露一面的龙套（车夫、掌柜、路人）不要建角色实体，把出场写进 events 或章节摘要即可。")
    lines.append("11. **原文对白**：重要度 ≥4 的角色必须在 `data.dialogue` 里摘 2–3 句本人原话（逐字，形如「第9章：原话」），供续写模仿口吻；程序会校验这些引文确实出现在本批正文里。")
    lines.append("12. **称呼习惯**：重要度 ≥4 且有对白的角色还要写 `data.address`——他怎么称呼别人、别人怎么称呼他、自称什么（例：「称墨大夫为墨老/您老，自称弟子」）；对话里能看出来的就写，看不出来就留空。")
    lines.append("")
    lines.append("## 实体类型")
    lines.append("")
    for k, v in protocol.ENTITY_TYPES.items():
        lines.append(f"- `{k}`：{v}")
    lines.append("")
    lines.append("## 角色卡 data 字段")
    lines.append("")
    for k, v in protocol.CHARACTER_DATA_FIELDS:
        lines.append(f"- `{k}`：{v}")
    lines.append("")
    lines.append("## 既有实体名册（用于复用名字/别名，不必重复建卡）")
    lines.append("")
    if roster:
        for r in roster:
            aliases = "、".join(r["aliases"]) if r["aliases"] else "—"
            lines.append(f"- [{r['etype']}] {r['name']}（别名：{aliases}；重要度 {r['importance']}）")
    else:
        lines.append("- （空，这是首批）")
    lines.append("")
    lines.append("## 本批正文")
    lines.append("")
    for ch in chapters:
        idx = int(ch["idx"])
        meta = f"### 第 {idx} 章 {ch.get('title') or ''}".rstrip()
        lines.append(meta)
        if truncations.get(idx):
            lines.append(f"> 本章超出 {MAX_CHAPTER_CHARS} 字，已截断；只抽取可见部分，摘要注明「本章未读全」。")
        lines.append("")
        lines.append(bodies[idx])
        lines.append("")
        lines.append(f"<!-- char_count={ch.get('char_count')} -->")
        lines.append("")
    return "\n".join(lines)


def build_packet(
    book_dir: Path,
    *,
    start: int | None = None,
    count: int = 5,
    force: bool = False,
) -> dict:
    manifest = load_manifest(book_dir)
    slug = manifest["slug"]
    if start is None:
        start = _next_start(book_dir, manifest)
    chapters = chapter_slice(manifest, start=start, count=count)
    if not chapters:
        raise ValueError(f"第 {start} 章之后没有章节了")
    bid = batch_id(int(chapters[0]["idx"]))
    pdir = book_dir / "packets" / bid
    if pdir.exists() and not force:
        raise FileExistsError(f"任务包已存在：{pdir}（用 --force 覆盖）")
    pdir.mkdir(parents=True, exist_ok=True)

    bodies: dict[int, str] = {}
    truncations: dict[int, bool] = {}
    for ch in chapters:
        body = read_chapter_body(book_dir, ch["body_path"])
        clipped, cut = _clip(body, MAX_CHAPTER_CHARS)
        bodies[int(ch["idx"])] = clipped
        truncations[int(ch["idx"])] = cut

    roster = entity_roster(book_dir)
    md = packet_markdown(
        manifest=manifest, batch=bid, chapters=chapters, bodies=bodies, roster=roster, truncations=truncations
    )
    chars = count_chars(md)
    if chars > MAX_PACKET_CHARS and len(chapters) > 1:
        # 超预算就减章重打包，保证单包可控
        return build_packet(book_dir, start=start, count=max(1, len(chapters) - 1), force=True)

    (pdir / "PACKET.md").write_text(md, encoding="utf-8")
    (pdir / "schema.json").write_text(protocol.schema_json(), encoding="utf-8")
    idxs = [int(c["idx"]) for c in chapters]
    (pdir / "result.template.json").write_text(protocol.template_json(slug, bid, idxs), encoding="utf-8")
    meta = {
        "book": slug,
        "title": manifest["title"],
        "batch": bid,
        "start_chapter": idxs[0],
        "end_chapter": idxs[-1],
        "chapters": [
            {
                "idx": int(c["idx"]),
                "number": c.get("number"),
                "title": c.get("title") or "",
                "char_count": c.get("char_count"),
                "body_path": c["body_path"],
                "truncated": truncations.get(int(c["idx"]), False),
            }
            for c in chapters
        ],
        "roster_size": len(roster),
        "packet_chars": chars,
        "tokens_est": estimate_tokens(chars),
        "schema": "schema.json",
        "template": "result.template.json",
    }
    (pdir / "packet.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "batch": bid,
        "dir": str(pdir),
        "chapters": idxs,
        "packet_chars": chars,
        "tokens_est": meta["tokens_est"],
        "files": ["PACKET.md", "packet.json", "schema.json", "result.template.json"],
        "truncated": [i for i, v in truncations.items() if v],
    }


def _next_start(book_dir: Path, manifest: dict) -> int:
    """从已 apply 的最后一批之后继续；没有批次记录就从第 1 章开始。"""
    rows = jsonl.read_jsonl(jsonl.path_for(book_dir, "batches"))
    applied = [r for r in rows if r.get("status") == "applied"]
    if applied:
        return max(int(r.get("end_chapter") or 0) for r in applied) + 1
    existing = sorted(p.name for p in (book_dir / "packets").glob("b*") if p.is_dir())
    if existing:
        meta_path = book_dir / "packets" / existing[-1] / "packet.json"
        if meta_path.exists():
            return int(json.loads(meta_path.read_text(encoding="utf-8"))["end_chapter"]) + 1
    return 1


def list_batches(book_dir: Path) -> list[dict]:
    out = []
    for p in sorted((book_dir / "packets").glob("b*")):
        meta_path = p / "packet.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["has_result"] = (book_dir / "results" / f"{p.name}.json").exists()
        out.append(meta)
    return out
