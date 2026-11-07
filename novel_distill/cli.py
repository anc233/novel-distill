"""命令行入口。所有子命令都支持 --json，退出码：0 成功 / 2 校验失败 / 3 数据缺失 / 4 未实现。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import (
    DEFAULT_BATCH_CHAPTERS,
    VAULT_SUBDIR,
    WORKSPACE,
    resolve_vault,
)
from .ingest.importer import add_book, load_manifest, split_report_md
from .util.log import error, info

EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_MISSING = 3
EXIT_TODO = 4


def _print_json(obj) -> None:
    info(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_init(args) -> int:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    info(f"[ok] workspace: {WORKSPACE}")
    info(f"[ok] vault: {resolve_vault(args.vault)} / {VAULT_SUBDIR}")
    return EXIT_OK


def cmd_doctor(args) -> int:
    from . import service

    rep = service.doctor(args.vault)
    if args.json:
        _print_json(rep)
    else:
        for c in rep["checks"]:
            info(f"[{'✓' if c['ok'] else '✗'}] {c['name']}: {c['detail']}")
        d = rep["defaults"]
        info(
            f"默认批次：{d['batch_chapters']} 章/包，"
            f"单章≤{d['max_chapter_chars']} 字，单包≤{d['max_packet_chars']} 字"
        )
    return EXIT_OK if rep["ok"] else EXIT_VALIDATION


def cmd_add(args) -> int:
    manifest = add_book(
        args.path,
        slug=args.slug,
        title=args.title,
        author=args.author or "",
        write_chapters=not args.no_chapters,
        overwrite=args.overwrite,
        max_heading_len=args.max_heading_len,
    )
    if args.json:
        _print_json({k: manifest[k] for k in ("slug", "title", "stats", "anomaly_counts", "source")})
    else:
        st = manifest["stats"]
        info(f"[ok] {manifest['title']} → workspace/{manifest['slug']}")
        info(
            f"     编码={manifest['source']['encoding']} 总字数={st['total_chars']:,} "
            f"卷={st['volume_count']} 章={st['chapter_count']} 归属率={st['coverage']:.2%}"
        )
        if manifest["anomaly_counts"]:
            info(f"     异常：{json.dumps(manifest['anomaly_counts'], ensure_ascii=False)} → split-report.md")
    return EXIT_OK


def cmd_split_report(args) -> int:
    manifest = load_manifest(args.slug)
    if args.markdown:
        info(split_report_md(manifest))
        return EXIT_OK
    if args.json:
        _print_json(
            {
                "slug": manifest["slug"],
                "stats": manifest["stats"],
                "anomaly_counts": manifest["anomaly_counts"],
                "anomalies": manifest["anomalies"],
            }
        )
        return EXIT_OK
    st = manifest["stats"]
    info(f"{manifest['title']}：{st['chapter_count']} 章 / {st['volume_count']} 卷 / 归属率 {st['coverage']:.2%}")
    for k, n in manifest["anomaly_counts"].items():
        info(f"  - {k}: {n}")
    return EXIT_OK


def cmd_stats(args) -> int:
    if getattr(args, "db", False):
        from .stats.report import collect
        from .stats.report import markdown as stats_markdown

        rep = collect(WORKSPACE / args.slug)
        if args.json:
            _print_json(rep)
        else:
            info(stats_markdown(rep))
        return EXIT_OK
    manifest = load_manifest(args.slug)
    st = dict(manifest["stats"])
    st["anomaly_counts"] = manifest["anomaly_counts"]
    st["clean"] = manifest["clean"]
    st["estimated_tokens"] = int(st["total_chars"] / 1.5)
    if args.write:
        out = Path(WORKSPACE) / args.slug / "exports"
        out.mkdir(parents=True, exist_ok=True)
        (out / "stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        _print_json(st)
    else:
        for k, v in st.items():
            info(f"{k}: {v}")
    return EXIT_OK


def cmd_rebuild_db(args) -> int:
    from .store.rebuild import rebuild_all, rebuild_book

    if args.all:
        if not WORKSPACE.exists():
            error(f"workspace 不存在：{WORKSPACE}")
            return EXIT_MISSING
        results = rebuild_all(WORKSPACE)
        if args.json:
            _print_json(results)
        else:
            for st in results:
                info(f"[ok] {st['book']}：{st['chapters']} 章 / 实体 {st['entities']} / 证据 {st['evidence']}")
        return EXIT_OK
    if not args.slug:
        error("需要书名 slug，或使用 --all")
        return EXIT_MISSING
    st = rebuild_book(WORKSPACE / args.slug)
    if args.json:
        _print_json(st)
    else:
        info(f"[ok] 重建 {st['book']} → {st['db']}")
        info(f"     卷/章 {st['volumes']}/{st['chapters']}，有正文 {st['chapters_with_body']}，实体 {st['entities']}，证据 {st['evidence']}")
        if st["unresolved_relations"]:
            info(f"     未解析关系 {st['unresolved_relations']} 条（实体尚未抽取）")
    return EXIT_OK


def cmd_query(args) -> int:
    from .store import db, repo

    db_file = WORKSPACE / args.slug / "book.db"
    if not db_file.exists():
        error(f"没有数据库：{db_file}（先运行 add 或 rebuild-db）")
        return EXIT_MISSING
    conn = db.connect(db_file)
    try:
        if args.what == "entity":
            if not args.value:
                error("需要实体名：query <slug> entity <名字>")
                return EXIT_MISSING
            ent = repo.get_entity(conn, args.slug, args.value)
            if ent is None:
                error(f"没有找到实体：{args.value}")
                return EXIT_MISSING
            if args.json:
                _print_json(ent)
            else:
                info(f"{ent['name']}（{ent['etype']}，重要度 {ent['importance']}，{ent['id']}）")
                if ent["aliases"]:
                    info(f"  别名：{'、'.join(ent['aliases'])}")
                if ent["summary"]:
                    info(f"  简介：{ent['summary']}")
                info(f"  首现/末现：第 {ent['first_chapter']} / {ent['last_chapter']} 章，证据 {len(ent['evidence'])} 条")
            return EXIT_OK
        if args.what == "list":
            rows = repo.list_entities(conn, args.slug, args.type)
            if args.json:
                _print_json(rows)
            else:
                if not rows:
                    info("（暂无实体）")
                for r in rows:
                    info(f"- {r['name']}（{r['etype']}，重要度 {r['importance']}）{'：' + r['summary'] if r['summary'] else ''}")
            return EXIT_OK
        if args.what == "search":
            if not args.value:
                error("需要关键词：query <slug> search <关键词>")
                return EXIT_MISSING
            rows = repo.search_chapters(conn, args.slug, args.value, args.limit)
            if args.json:
                _print_json(rows)
            else:
                for r in rows:
                    info(f"- 第{r['idx']}章 {r['title']}：{r['snip']}")
            return EXIT_OK
        if args.what == "stats":
            st = repo.stats(conn, args.slug)
            if args.json:
                _print_json(st)
            else:
                for k, v in st.items():
                    info(f"{k}: {v}")
            return EXIT_OK
        if args.what in ("volume", "chapter"):
            from .store import inspect as insp

            if not args.value:
                error(f"需要编号：query <slug> {args.what} <N>")
                return EXIT_MISSING
            try:
                num = int(args.value)
            except ValueError:
                error(f"编号必须是整数：{args.value}")
                return EXIT_MISSING
            data = (insp.volume if args.what == "volume" else insp.chapter)(conn, args.slug, num)
            if data is None:
                error(f"没有第 {num} {'卷' if args.what == 'volume' else '章'}")
                return EXIT_MISSING
            if args.json:
                _print_json(data)
            elif args.what == "volume":
                info(f'第{data["idx"]}卷 {data["title"]}（第 {data["lo"]}–{data["hi"]} 章，{data["summarized"]}/{data["chapter_count"]} 章已摘要）')
                if data["entities"]:
                    info("  实体：" + "、".join(f'{e["name"]}（{e["etype"]}）' for e in data["entities"][:12]))
                if data["foreshadowings"]:
                    info("  本卷伏笔：" + "、".join(f["title"] for f in data["foreshadowings"][:8]))
                if data["events"]:
                    info("  事件：" + "、".join(f'第{e["chapter_idx"]}章 {e["title"]}' for e in data["events"][:8]))
                info(f'  证据 {data["evidence"]} 条')
            else:
                info(f'第{data["idx"]}章 {data["title"]}（第{data["volume"]}卷 {data["volume_title"] or ""}，{data["char_count"]} 字）')
                if data["summary"]:
                    info(f'  摘要：{data["summary"]}')
                if data["entities"]:
                    info("  出场：" + "、".join(e["name"] for e in data["entities"]))
                if data["events"]:
                    info("  事件：" + "、".join(e["title"] for e in data["events"]))
                if data["foreshadowings"]:
                    info("  本批埋伏笔：" + "、".join(f["title"] for f in data["foreshadowings"]))
            return EXIT_OK
    finally:
        conn.close()
    error(f"未知查询类型：{args.what}")
    return EXIT_VALIDATION


def cmd_pack(args) -> int:
    from .tasks.packet import build_packet, list_batches

    bdir = WORKSPACE / args.slug
    if not bdir.exists():
        error(f"没有这本书：{bdir}")
        return EXIT_MISSING
    if args.list:
        rows = list_batches(bdir)
        if args.json:
            _print_json(rows)
        else:
            for r in rows:
                flag = "✓" if r["has_result"] else " "
                info(f"[{flag}] {r['batch']} 第 {r['start_chapter']}–{r['end_chapter']} 章  ~{r['tokens_est']} tokens")
        return EXIT_OK
    try:
        out = build_packet(bdir, start=args.start, count=args.count, force=args.force)
    except FileExistsError as exc:
        error(str(exc))
        return EXIT_VALIDATION
    except ValueError as exc:
        error(str(exc))
        return EXIT_MISSING
    if args.json:
        _print_json(out)
    else:
        info(f"[ok] 任务包 {out['batch']} → {out['dir']}")
        info(f"     章节 {out['chapters'][0]}–{out['chapters'][-1]}，{out['packet_chars']:,} 字 ≈ {out['tokens_est']:,} tokens")
        if out["truncated"]:
            info(f"     ⚠ 超长截断：第 {out['truncated']} 章")
        info(f"     下一步：读 PACKET.md，写 results/{out['batch']}.json，然后 validate + apply")
    return EXIT_OK


def cmd_repair_spans(args) -> int:
    from .store.repair import recompute_entity_spans

    bdir = WORKSPACE / args.slug
    if not bdir.exists():
        error(f"没有这本书：{bdir}")
        return EXIT_MISSING
    res = recompute_entity_spans(bdir, dry_run=args.dry_run)
    if args.json:
        _print_json(res)
    else:
        info(f"[ok] 扫描 {res['scanned']} 个实体，修正 {res['changed']} 个章号跨度（dry-run={res['dry_run']}）")
        for c in res["changes"][:20]:
            info(f"  - {c['name']}：{c['old']} → {c['new']}")
    return EXIT_OK


def cmd_retype(args) -> int:
    from .store.migrate import retype
    from .store.rebuild import rebuild_book

    bdir = WORKSPACE / args.slug
    if not bdir.exists():
        error(f"没有这本书：{bdir}")
        return EXIT_MISSING
    try:
        res = retype(bdir, args.name, args.etype, book=args.slug, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as exc:
        error(str(exc))
        return EXIT_MISSING
    if args.rebuild and res["changed"] and not args.dry_run:
        res["rebuild"] = {
            k: v for k, v in rebuild_book(bdir).items() if k in ("entities", "relations", "evidence", "chapters")
        }
    if args.json:
        _print_json(res)
    elif res["changed"]:
        info(f"[ok] {res['name']}：{res.get('old_etype')} → {res['new_etype']}（id {res.get('old_id')} → {res['new_id']}）")
    else:
        info(f"[=] {res['name']} 已经是 {res['etype']}，无需迁移")
    return EXIT_OK


def _report_lines(rep) -> list[str]:
    lines = [f"校验 {'通过' if rep.ok else '失败'}：{len(rep.errors)} error / {len(rep.warnings)} warning / {len(rep.conflicts)} conflict"]
    lines.extend(f"  [E:{e.code}] {e.where} {e.message}" for e in rep.errors[:20])
    lines.extend(f"  [W:{w.code}] {w.where} {w.message}" for w in rep.warnings[:10])
    lines.extend(f"  [C] {c['kind']}: {c['detail']}" for c in rep.conflicts[:10])
    return lines


def cmd_validate(args) -> int:
    from .codex.apply import result_path
    from .codex.validate import validate_file

    bdir = WORKSPACE / args.slug
    path = result_path(bdir, args.batch)
    if not path.exists():
        error(f"没有结果文件：{path}")
        return EXIT_MISSING
    rep = validate_file(bdir, path)
    if args.json:
        _print_json(rep.as_dict())
    else:
        for line in _report_lines(rep):
            info(line)
        info(f"统计：{rep.stats}")
    return EXIT_OK if rep.ok else EXIT_VALIDATION


def cmd_apply(args) -> int:
    from .codex.apply import apply_result

    bdir = WORKSPACE / args.slug
    try:
        out = apply_result(bdir, args.batch, force=args.force, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        error(str(exc))
        return EXIT_MISSING
    if args.json:
        _print_json(out)
    else:
        if not out.get("applied"):
            info(f"未入库：{out.get('reason') or 'dry-run'}")
            for e in out.get("errors", [])[:20]:
                info(f"  [E:{e['code']}] {e['where']} {e['message']}")
            if out.get("counts"):
                info(f"  将写入：{out['counts']}")
        else:
            info(f"[ok] {out['batch']} 已入库（第 {out['chapters'][0]}–{out['chapters'][1]} 章）")
            info(f"     写入：{ dict(out['counts'].items()) }")
            if out["conflicts"]:
                info(f"     ⚠ {out['conflicts']} 条待裁决冲突 → 见 query / conflicts 表")
            info(f"     当前总量：实体 {out['stats']['entities']} / 关系 {out['stats']['relations']} / 证据 {out['stats']['evidence']}")
    return EXIT_OK if out.get("applied") else EXIT_VALIDATION


def cmd_render(args) -> int:
    from .render.obsidian import render_book

    bdir = WORKSPACE / args.slug
    out = render_book(bdir, vault=args.vault, clean=args.clean, plain_links=args.plain_links)
    if args.json:
        _print_json(out)
    else:
        info(f"[ok] 已渲染 {out['files']} 个文件 → {out['vault']}")
        st = out["stats"]
        info(f"     实体 {st['entities']} / 关系 {st['relations']} / 证据 {st['evidence']} / 伏笔 {sum(st['foreshadowings'].values())}")
        for p in out["written"][:12]:
            info(f"     - {p}")
    return EXIT_OK


def cmd_voice(args) -> int:
    from .render.voice import build

    out = build(
        WORKSPACE / args.slug,
        min_importance=args.min_importance,
        limit=args.limit,
        out=args.out,
        vault=args.vault,
    )
    if args.json:
        _print_json(out)
    else:
        info(f'[ok] 人物口吻卡 → {out["path"]}')
        info(f'     角色 {out["characters"]} 人，{out["chars"]} 字 ≈ {out["tokens_est"]} tokens')
    return EXIT_OK


def cmd_lint(args) -> int:
    from .store import lint as lint_mod

    rep = lint_mod.lint(WORKSPACE / args.slug, vault=args.vault, vault_links=not args.no_links)
    wrote = None
    if args.write:
        root = Path(resolve_vault(args.vault)) / VAULT_SUBDIR / rep["book"]
        target = root / "99 统计" / "自检报告.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(lint_mod.markdown(rep), encoding="utf-8")
        wrote = str(target)
    if args.json:
        payload = dict(rep)
        if wrote:
            payload["report_path"] = wrote
        _print_json(payload)
    else:
        info(f'{rep["book"]}：蒸馏到第 {rep["upto"]} 章，问题 {len(rep["problems"])} 条'
             + ("（有阻断级）" if not rep["ok"] else ""))
        for p in rep["problems"]:
            mark = "⛔" if p["level"] == "error" else "⚠️"
            info(f"  {mark} [{p['kind']}] {p['detail']}")
        if wrote:
            info(f"     报告 → {wrote}")
    return EXIT_OK if rep["ok"] else EXIT_VALIDATION


def cmd_keywords(args) -> int:
    from .ingest import keywords

    rep = keywords.collect(WORKSPACE / args.slug, start=args.start, count=args.count, top=args.top)
    if args.json:
        _print_json(rep)
    else:
        info(f"第 {rep['range'][0]}–{rep['range'][1]} 章，{rep['chars']} 字，引擎 {rep['engine']}")
        info("新人名候选：")
        if not rep["new_names"]:
            info("  （无）")
        for r in rep["new_names"]:
            snip = ("  " + r["snippet"][:30]) if r.get("snippet") else ""
            info(f"  {r['name']} ×{r['count']}（{r['chapters']} 章）{snip}")
        if args.write:
            root = Path(resolve_vault(args.vault)) / VAULT_SUBDIR / rep["book"]
            target = root / "99 统计" / f"关键词-{rep['range'][0]:04d}-{rep['range'][1]:04d}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(keywords.markdown(rep), encoding="utf-8")
            info(f"     报告 → {target}")
    return EXIT_OK


def cmd_dedup(args) -> int:
    from .store import dedup

    try:
        out = dedup.find_duplicates(
            WORKSPACE / args.slug,
            threshold=args.threshold,
            min_chars=args.min_chars,
            num_perm=args.num_perm,
        )
    except ImportError as exc:
        error(f'dedup 需要 datasketch 与 numpy/scipy：pip install "novel-distill[dedup]"（{exc}）')
        return EXIT_MISSING
    except ValueError as exc:
        error(str(exc))
        return EXIT_MISSING
    except FileNotFoundError as exc:
        error(str(exc))
        return EXIT_MISSING
    if args.json:
        _print_json(out)
        return EXIT_OK
    if not out["pairs"]:
        info(
            f'{out["compared"]} 章参与比对（{out["skipped"]} 章短于 {args.min_chars} 字跳过），'
            f'未发现 Jaccard ≥ {out["threshold"]} 的章节对。'
        )
        return EXIT_OK
    info(f'发现 {len(out["pairs"])} 对高度相似章节（阈值 {out["threshold"]}）：')
    for p in out["pairs"]:
        info(f'  第 {p["a"]} 章 ≈ 第 {p["b"]} 章（{p["jaccard"]:.2%}）')
        info(f'    {p["a_title"] or "（无标题）"} | {p["b_title"] or "（无标题）"}')
    return EXIT_OK


def cmd_pack_continue(args) -> int:
    from .pack.continue_pack import build

    out = build(WORKSPACE / args.slug, upto=args.upto, recent=args.recent, style_sample=args.style_sample)
    if args.json:
        _print_json(out)
    else:
        info(f"[ok] 续写上下文包 → {out['path']}")
        info(f"     蒸馏到第 {out['upto']} / {out['chapters_total']} 章，人物 {out['characters']}，未回收伏笔 {out['foreshadowings']}")
        info(f"     {out['chars']} 字 ≈ {out['tokens_est']} tokens")
        info(f"     vault: {out['vault_path']}")
    return EXIT_OK


def cmd_mcp(args) -> int:
    try:
        from . import mcp_server
    except ImportError as exc:
        error(f'MCP 需要官方 SDK：pip install "novel-distill[mcp]"（{exc}）')
        return EXIT_MISSING
    mcp_server.main()
    return EXIT_OK


def cmd_gui(args) -> int:
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        error(f"GUI 需要 tkinter（Python 自带）或 customtkinter：{exc}")
        return EXIT_MISSING
    return int(gui_main(self_test=getattr(args, "self_test", False), lang=getattr(args, "lang", None)))


def _todo(name: str, stage: str) -> int:
    error(f"{name} 尚未实现（计划阶段 {stage}）")
    return EXIT_TODO


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="novel_distill", description="网络小说蒸馏工坊")
    p.add_argument("--version", action="version", version=f"novel_distill {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化工作区")
    s.add_argument("--vault")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="环境自检")
    s.add_argument("--json", action="store_true")
    s.add_argument("--vault")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("add", help="导入一本书并切章")
    s.add_argument("path")
    s.add_argument("--slug")
    s.add_argument("--title")
    s.add_argument("--author")
    s.add_argument("--no-chapters", action="store_true", help="不写分章 md")
    s.add_argument("--overwrite", action="store_true")
    s.add_argument("--max-heading-len", type=int, default=80)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("split-report", help="查看切章报告")
    s.add_argument("slug")
    s.add_argument("--json", action="store_true")
    s.add_argument("--markdown", action="store_true")
    s.set_defaults(func=cmd_split_report)

    s = sub.add_parser("stats", help="统计（语料层；--db 看设定层与覆盖率）")
    s.add_argument("slug")
    s.add_argument("--db", action="store_true", help="统计设定层（实体/证据/覆盖率/待补卡）")
    s.add_argument("--json", action="store_true")
    s.add_argument("--write", action="store_true")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("rebuild-db", help="从 manifest/分章/codex JSONL 重建数据库")
    s.add_argument("slug", nargs="?")
    s.add_argument("--all", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_rebuild_db)

    s = sub.add_parser("query", help="查询设定（entity/list/search/stats）")
    s.add_argument("slug")
    s.add_argument("what", choices=["entity", "list", "search", "stats", "volume", "chapter"])
    s.add_argument("value", nargs="?")
    s.add_argument("--type")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("repair-spans", help="修复：按证据/关系/事件重算实体章号跨度")
    s.add_argument("slug")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_repair_spans)

    s = sub.add_parser("retype", help="迁移：改实体类型并重算 ID（如 material → pill）")
    s.add_argument("slug")
    s.add_argument("name")
    s.add_argument("etype")
    s.add_argument("--rebuild", action="store_true", help="迁移后自动重建数据库")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_retype)

    s = sub.add_parser("pack", help="生成抽取任务包（P4）")
    s.add_argument("slug")
    s.add_argument("--from", dest="start", type=int, default=None, help="起始章号；缺省自动接续")
    s.add_argument("--count", type=int, default=DEFAULT_BATCH_CHAPTERS)
    s.add_argument("--force", action="store_true")
    s.add_argument("--list", action="store_true", help="列出已有任务包")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_pack)

    s = sub.add_parser("validate", help="校验抽取结果（P3，V1–V17）")
    s.add_argument("slug")
    s.add_argument("batch")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("apply", help="校验并入库（P3，单事务幂等）")
    s.add_argument("slug")
    s.add_argument("batch")
    s.add_argument("--force", action="store_true", help="有 error 也强行入库（不推荐）")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("render", help="渲染到 Obsidian（P5）")
    s.add_argument("slug")
    s.add_argument("--vault", help="Obsidian vault 根目录（缺省读 obsidian.json）")
    s.add_argument("--clean", action="store_true", help="先清空该书的渲染目录")
    s.add_argument(
        "--plain-links",
        action="store_true",
        help="输出标准 Markdown 相对链接（给没有 Obsidian 的编辑器用；默认是 Obsidian 双链）",
    )
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("voice", help="导出人物口吻卡（P7）")
    s.add_argument("slug")
    s.add_argument("--min-importance", type=int, default=4)
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--out")
    s.add_argument("--vault")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_voice)

    s = sub.add_parser("keywords", help="抽取某批章节的关键词与新人名候选")
    s.add_argument("slug")
    s.add_argument("--from", dest="start", type=int, default=1, help="起始章号")
    s.add_argument("--count", type=int, default=5, help="取多少章")
    s.add_argument("--top", type=int, default=30)
    s.add_argument("--write", action="store_true", help="写入 vault 99 统计/关键词-xxxx-xxxx.md")
    s.add_argument("--vault")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_keywords)

    s = sub.add_parser("lint", help="设定库自检（缺口/冲突/未渲染/断链）")
    s.add_argument("slug")
    s.add_argument("--vault")
    s.add_argument("--no-links", dest="no_links", action="store_true", help="不检查 vault 双链（不依赖 obsidiantools）")
    s.add_argument("--write", action="store_true", help="写入 vault 99 统计/自检报告.md")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("dedup", help="查近重复章节（MinHash+LSH，需 datasketch）")
    s.add_argument("slug")
    s.add_argument("--threshold", type=float, default=0.8, help="Jaccard 阈值（默认 0.8）")
    s.add_argument("--min-chars", dest="min_chars", type=int, default=200, help="少于这么多字的章节不参与比对")
    s.add_argument("--num-perm", dest="num_perm", type=int, default=128, help="MinHash 置换数；阈值越高需要越大")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_dedup)

    s = sub.add_parser("pack-continue", help="生成续写上下文包（P7）")
    s.add_argument("slug")
    s.add_argument("--upto", type=int, default=None, help="蒸馏到第几章（缺省取已有摘要的最大章号）")
    s.add_argument("--recent", type=int, default=12, help="带多少章最近摘要")
    s.add_argument("--style-sample", dest="style_sample", action="store_true", default=True, help="附最近 3 章各 2 段原文（默认开）")
    s.add_argument("--no-style-sample", dest="style_sample", action="store_false", help="不附原文样本")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_pack_continue)

    s = sub.add_parser("mcp", help="启动 MCP server（stdio），供 Claude Code / Cursor / Codex 等调用")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("gui", help="启动图形界面")
    s.add_argument("--self-test", dest="self_test", action="store_true", help="只构建界面后退出（打包验证用）")
    s.add_argument("--lang", choices=["zh", "en"], default=None, help="界面语言（缺省读设置或中文）")
    s.set_defaults(func=cmd_gui)
    return p


def _hide_console() -> None:
    """双击 GUI 时藏掉控制台窗口；命令行调用不会走到这里。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:  # noqa: BLE001, S110 - 无控制台/受限环境时静默忽略
        pass


def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) == 1:
        from .config import FROZEN

        if FROZEN:  # 双击 exe：默认进 GUI，而不是 argparse 报错
            _hide_console()
            from .gui import main as gui_main

            return int(gui_main())
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "json"):
        args.json = False
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        error(str(exc))
        return EXIT_MISSING
    except KeyboardInterrupt:
        error("已中断")
        return 130
