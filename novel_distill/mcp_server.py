"""MCP server（stdio）：把 novel-distill 的服务层暴露给任意 MCP 客户端。

用法：
    python -m novel_distill mcp          # 或 novel-distill mcp
    novel-distill-mcp                     # 安装后的 console script

客户端配置示例（Claude Code / Cursor / Codex 见 docs/MCP.md）。
写操作默认允许；apply_result / render_book 需要显式 confirm=True。
设置环境变量 NOVEL_DISTILL_READONLY=1 可一键只读。
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, service

INSTRUCTIONS = """novel-distill 是中文网络小说蒸馏工坊：把整本小说切章入库，按批生成 LLM 任务包，
校验/入库模型产出的结构化 JSON，再渲染成 Obsidian 笔记。

推荐工作流：
1. list_books() 看已有书籍；没有就 add_book(path=绝对路径, title=书名)。
2. book_stats(slug) 确认章节与蒸馏进度。
3. make_packet(slug, start, count) 生成任务包 → 读取返回的 packet_md 文件。
4. 模型写完 results/<batch>.json 后 validate_result(slug, batch)。
5. 校验通过后 apply_result(slug, batch, confirm=True) 写库。
6. render_book(slug, confirm=True) 写 Obsidian vault。
7. audit_book(slug) 做一次体检（lint + 双链 + 近重复）。

约定：slug 是书籍目录名（如 fanshen-xiuxian）；所有路径为绝对路径；
写操作失败会返回 [code] message 形式的错误；只读模式下写工具直接拒绝。
"""

server = MCPServer(
    name="novel-distill",
    version=__version__,
    instructions=INSTRUCTIONS,
)


def _wrap(call, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(*args, **kwargs)
    except service.ServiceError as exc:
        raise ValueError(f"[{exc.code}] {exc.message}") from exc


@server.tool()
def doctor(vault: str | None = None) -> dict:
    """环境自检：Python/SQLite FTS5/workspace/vault/git/jieba。"""
    return _wrap(service.doctor, vault)


@server.tool()
def list_books() -> dict:
    """列出工作区内所有已导入的书（slug、书名、作者、章节数、库内统计）。"""
    books = service.list_books()
    return {"books": books, "count": len(books)}


@server.tool()
def add_book(path: str, title: str | None = None, author: str = "", overwrite: bool = False) -> dict:
    """导入一本小说 txt：复制、编码归一、清洗、切卷切章并建库。path 为绝对路径。"""
    return _wrap(service.import_book, path, title=title, author=author, overwrite=overwrite)


@server.tool()
def book_stats(slug: str) -> dict:
    """书籍统计：章节/实体/关系/证据/伏笔/事件/摘要/批次进度。"""
    return _wrap(service.stats, slug)


@server.tool()
def make_packet(slug: str, start: int = 1, count: int = 5, force: bool = False) -> dict:
    """生成第 start 章起 count 章的任务包，返回包目录、PACKET.md 路径与 token 估算。"""
    return _wrap(service.make_packet, slug, start=start, count=count, force=force)


@server.tool()
def list_batches(slug: str) -> dict:
    """列出已生成的任务包批次及其是否已有结果文件。"""
    batches = _wrap(service.batches, slug)
    return {"batches": batches, "count": len(batches)}


@server.tool()
def validate_result(slug: str, batch: str) -> dict:
    """按 V1–V17 规则 + JSON Schema 校验 results/<batch>.json，返回错误明细。"""
    return _wrap(service.validate, slug, batch)


@server.tool()
def apply_result(slug: str, batch: str, confirm: bool = False, dry_run: bool = False, force: bool = False) -> dict:
    """把校验通过的结果写入数据库。必须显式传 confirm=True（dry_run 除外）。"""
    return _wrap(service.apply, slug, batch, confirm=confirm, dry_run=dry_run, force=force)


@server.tool()
def query_entity(slug: str, name: str) -> dict:
    """按名字或别名查一个实体：属性、关系、证据、首现/末现章节。"""
    return _wrap(service.entity, slug, name)


@server.tool()
def list_entities(slug: str, etype: str | None = None, limit: int = 200) -> dict:
    """列出实体，可按类型过滤：character/pill/technique/world_rule/artifact/faction/dungeon/arc/material。"""
    items = _wrap(service.entities, slug, etype=etype, limit=limit)
    return {"entities": items, "count": len(items)}


@server.tool()
def search_chapters(slug: str, query: str, limit: int = 10) -> dict:
    """全文检索章节（FTS5），返回章节号、标题与命中片段。"""
    hits = _wrap(service.search, slug, query, limit=limit)
    return {"matches": hits, "count": len(hits)}


@server.tool()
def inspect_chapter(slug: str, number: int, kind: str = "chapter") -> dict:
    """查看第 N 章或第 N 卷的详细内容（kind=chapter|volume）。"""
    return _wrap(service.inspect, slug, kind, number)


@server.tool()
def audit_book(
    slug: str,
    vault: str | None = None,
    threshold: float = 0.9,
    min_chars: int = 2000,
    num_perm: int = 128,
) -> dict:
    """一键体检：自检（数量/覆盖/断链/孤立笔记）+ 近重复章节检测。"""
    return _wrap(
        service.audit,
        slug,
        vault=vault,
        threshold=threshold,
        min_chars=min_chars,
        num_perm=num_perm,
    )


@server.tool()
def render_book(
    slug: str, confirm: bool = False, clean: bool = False, vault: str | None = None, plain_links: bool = False
) -> dict:
    """把库内容渲染成 Obsidian 笔记（会写 vault）。必须显式传 confirm=True。

    plain_links=True 时输出标准 Markdown 相对链接，方便没有 Obsidian 的编辑器直接点开。
    """
    return _wrap(service.render, slug, vault=vault, clean=clean, plain_links=plain_links, confirm=confirm)


@server.tool()
def keyword_report(slug: str, start: int = 1, count: int = 5, top: int = 40) -> dict:
    """统计指定章节区间的新人名候选与高频词，用于补实体。"""
    return _wrap(service.keywords, slug, start=start, count=count, top=top)


@server.tool()
def continuity_pack(slug: str, upto: int | None = None, recent: int = 12) -> dict:
    """生成续写上下文包（未回收伏笔、人物口吻、近期摘要）。"""
    return _wrap(service.continuity, slug, upto=upto, recent=recent)


@server.tool()
def vault_links(vault: str | None = None) -> dict:
    """检查 Obsidian vault 的断链与孤立笔记（不写任何文件）。"""
    return service.vault_links(vault)


def main() -> None:
    """启动 stdio MCP server。"""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

