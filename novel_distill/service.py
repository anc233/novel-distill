"""统一服务层：CLI / MCP / GUI 共用的纯函数接口。

所有函数返回 JSON 可序列化的 dict，写操作抛 :class:`ServiceError`（带 code）。
环境变量：
- NOVEL_DISTILL_WORKSPACE   覆盖工作区目录
- NOVEL_DISTILL_VAULT       覆盖 Obsidian vault 根
- NOVEL_DISTILL_READONLY=1  只读模式，所有写操作直接拒绝
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_BATCH_CHAPTERS,
    MAX_CHAPTER_CHARS,
    MAX_PACKET_CHARS,
    resolve_vault,
)
from .config import (
    WORKSPACE as _CONFIG_WORKSPACE,
)

EXIT_OK = 0
EXIT_VALIDATION = 2
EXIT_MISSING = 3


class ServiceError(Exception):
    """带错误码的服务异常；MCP/GUI 直接展示 message。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def workspace() -> Path:
    raw = os.environ.get("NOVEL_DISTILL_WORKSPACE")
    return Path(raw) if raw else Path(_CONFIG_WORKSPACE)


def readonly() -> bool:
    return os.environ.get("NOVEL_DISTILL_READONLY", "").strip() in {"1", "true", "yes"}


def _require_write(action: str) -> None:
    if readonly():
        raise ServiceError("readonly", f"只读模式（NOVEL_DISTILL_READONLY=1）下不能{action}")


def _book_dir(slug: str) -> Path:
    if not slug:
        raise ServiceError("missing", "缺少书名 slug")
    bdir = workspace() / slug
    if not bdir.is_dir():
        raise ServiceError("missing", f"没有这本书：{bdir}（先用 list_books 查看，或 add_book 导入）")
    return bdir


def _connect(slug: str):
    from .store import db

    bdir = _book_dir(slug)
    db_file = bdir / "book.db"
    if not db_file.exists():
        raise ServiceError("missing", f"没有数据库：{db_file}（先 add_book 或 rebuild_db）")
    return db.connect(db_file)


def _read_manifest(bdir: Path) -> dict:
    path = bdir / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def list_books() -> list[dict]:
    """列出工作区内的书（读取 manifest.json，附带库内统计）。"""
    root = workspace()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for bdir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = _read_manifest(bdir)
        if not manifest:
            continue
        stats: dict = {}
        db_file = bdir / "book.db"
        if db_file.exists():
            try:
                conn = _open_db(db_file)
                try:
                    stats = _stats_of(conn, manifest.get("slug") or bdir.name)
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001 - 统计失败不影响列表
                stats = {}
        out.append(
            {
                "slug": manifest.get("slug") or bdir.name,
                "title": manifest.get("title") or bdir.name,
                "author": manifest.get("author") or "",
                "chapters": len(manifest.get("chapters") or []),
                "total_chars": (manifest.get("stats") or {}).get("total_chars", 0),
                "dir": str(bdir),
                "batch_chapters": manifest.get("batch_chapters"),
                "stats": stats,
            }
        )
    return out


def _open_db(path: Path):
    from .store import db

    return db.connect(path)


def _stats_of(conn, slug: str) -> dict:
    from .store import repo

    return repo.stats(conn, slug)


def doctor(vault: str | Path | None = None) -> dict:
    """环境自检（与 CLI doctor 同一套检查）。"""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("Python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0])
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
            fts = True
        except sqlite3.OperationalError:
            fts = False
        conn.close()
    except Exception:  # noqa: BLE001 - doctor 要报告失败而不是崩溃
        fts = False
    add("SQLite FTS5", fts, sqlite3.sqlite_version)

    ws = workspace()
    try:
        ws.mkdir(parents=True, exist_ok=True)
        probe = ws / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("workspace 可写", True, str(ws))
    except Exception as exc:  # noqa: BLE001 - 写探针可能抛任意 OSError
        add("workspace 可写", False, str(exc))

    vpath = resolve_vault(str(vault) if vault else None)
    explicit_vault = bool(vault) or bool(os.environ.get("NOVEL_DISTILL_VAULT"))
    if vpath.exists():
        add("Obsidian vault 存在", True, str(vpath))
    elif explicit_vault:
        # 用户明确指定了却不存在，多半是路径写错，要报出来。
        add("Obsidian vault 存在", False, f"{vpath}（指定路径不存在）")
    else:
        # 没装 Obsidian、也没配置 vault：渲染时会自动建这个目录，仍可正常使用。
        add("Obsidian vault（可选）", True, f"未设置，渲染时用 --vault 指定目录或在 GUI 设置页选择（默认 {vpath}，会自动创建）")
    add("git 可用", shutil.which("git") is not None, shutil.which("git") or "未安装")
    try:
        jieba = importlib.util.find_spec("jieba") is not None
    except Exception:  # noqa: BLE001 - find_spec 在坏路径上会抛 ValueError/OSError
        jieba = False
    add("jieba（可选）", True, "已安装" if jieba else "未安装，将退化为字符 n-gram")
    optional = {"jieba（可选）"}
    ok = all(c["ok"] for c in checks if c["name"] not in optional)
    return {
        "ok": ok,
        "checks": checks,
        "workspace": str(ws),
        "vault": str(vpath),
        "defaults": {
            "batch_chapters": DEFAULT_BATCH_CHAPTERS,
            "max_chapter_chars": MAX_CHAPTER_CHARS,
            "max_packet_chars": MAX_PACKET_CHARS,
        },
    }


def import_book(
    src: str | Path,
    *,
    slug: str | None = None,
    title: str | None = None,
    author: str = "",
    write_chapters: bool = True,
    overwrite: bool = False,
) -> dict:
    _require_write("导入书籍")
    from .ingest.importer import add_book

    try:
        manifest = add_book(
            src,
            slug=slug,
            title=title,
            author=author,
            workdir=workspace(),
            write_chapters=write_chapters,
            overwrite=overwrite,
        )
    except FileNotFoundError as exc:
        raise ServiceError("missing", str(exc)) from exc
    return {
        "slug": manifest.get("slug"),
        "title": manifest.get("title"),
        "author": manifest.get("author"),
        "chapters": len(manifest.get("chapters") or []),
        "volumes": len(manifest.get("volumes") or []),
        "total_chars": (manifest.get("stats") or {}).get("total_chars", 0),
        "dir": str(workspace() / (manifest.get("slug") or "")),
        "stats": manifest.get("stats"),
    }


def stats(slug: str) -> dict:
    bdir = _book_dir(slug)
    db_file = bdir / "book.db"
    if not db_file.exists():
        raise ServiceError("missing", f"没有数据库：{db_file}（先 add_book 或 rebuild_db）")
    conn = _open_db(db_file)
    try:
        return _stats_of(conn, slug)
    finally:
        conn.close()


def make_packet(slug: str, *, start: int = 1, count: int | None = None, force: bool = False) -> dict:
    _require_write("生成任务包")
    from .tasks.packet import build_packet

    try:
        return build_packet(_book_dir(slug), start=start, count=count or DEFAULT_BATCH_CHAPTERS, force=force)
    except FileExistsError as exc:
        raise ServiceError("validation", str(exc)) from exc
    except ValueError as exc:
        raise ServiceError("missing", str(exc)) from exc


def batches(slug: str) -> list[dict]:
    from .tasks.packet import list_batches

    return list_batches(_book_dir(slug))


def validate(slug: str, batch: str) -> dict:
    from .codex.apply import result_path
    from .codex.validate import validate_file

    bdir = _book_dir(slug)
    path = result_path(bdir, batch)
    if not path.exists():
        raise ServiceError("missing", f"没有结果文件：{path}")
    rep = validate_file(bdir, path)
    return rep.as_dict()


def apply(
    slug: str,
    batch: str,
    *,
    force: bool = False,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict:
    _require_write("写库")
    if not dry_run and not confirm:
        raise ServiceError(
            "confirm_required",
            "写库前必须显式传 confirm=True：先 validate_result 通过，再 apply_result(confirm=True)。",
        )
    from .codex.apply import apply_result

    try:
        return apply_result(_book_dir(slug), batch, force=force, dry_run=dry_run)
    except FileNotFoundError as exc:
        raise ServiceError("missing", str(exc)) from exc


def render(
    slug: str, *, vault: str | None = None, clean: bool = False, plain_links: bool = False, confirm: bool = False
) -> dict:
    _require_write("写 vault")
    if not confirm:
        raise ServiceError("confirm_required", "渲染会写 Obsidian vault，请传 confirm=True 确认。")
    from .render.obsidian import render_book

    try:
        return render_book(_book_dir(slug), vault=vault, clean=clean, plain_links=plain_links)
    except (FileNotFoundError, ValueError) as exc:
        raise ServiceError("missing", str(exc)) from exc


def entity(slug: str, name: str) -> dict:
    from .store import repo

    conn = _connect(slug)
    try:
        ent = repo.get_entity(conn, slug, name)
    finally:
        conn.close()
    if ent is None:
        raise ServiceError("missing", f"没有找到实体：{name}")
    return ent


def entities(slug: str, *, etype: str | None = None, limit: int = 200) -> list[dict]:
    from .store import repo

    conn = _connect(slug)
    try:
        return repo.list_entities(conn, slug, etype, limit)
    finally:
        conn.close()


def search(slug: str, query: str, *, limit: int = 10) -> list[dict]:
    from .store import repo

    if not query:
        raise ServiceError("missing", "缺少搜索关键词")
    conn = _connect(slug)
    try:
        return repo.search_chapters(conn, slug, query, limit)
    finally:
        conn.close()


def inspect(slug: str, what: str, num: int) -> dict:
    from .store import inspect as insp

    conn = _connect(slug)
    try:
        data = (insp.volume if what == "volume" else insp.chapter)(conn, slug, int(num))
    finally:
        conn.close()
    if data is None:
        raise ServiceError("missing", f"没有第 {num} {'卷' if what == 'volume' else '章'}")
    return data


def lint(slug: str, *, vault: str | None = None, vault_links: bool = True, write_report: bool = False) -> dict:
    from .store import lint as lint_mod

    rep = lint_mod.lint(_book_dir(slug), vault=vault, vault_links=vault_links)
    if write_report:
        _require_write("写自检报告")
        root = Path(resolve_vault(vault)) / _vault_subdir() / rep["book"]
        target = root / "99 统计" / "自检报告.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(lint_mod.markdown(rep), encoding="utf-8")
        rep = dict(rep)
        rep["report_path"] = str(target)
    return rep


def _vault_subdir() -> str:
    from .config import VAULT_SUBDIR

    return VAULT_SUBDIR


def dedup(slug: str, *, threshold: float = 0.9, min_chars: int = 2000, num_perm: int = 128) -> dict:
    from .store import dedup as dedup_mod

    try:
        return dedup_mod.find_duplicates(
            _book_dir(slug), threshold=threshold, min_chars=min_chars, num_perm=num_perm
        )
    except ImportError as exc:
        raise ServiceError(
            "missing",
            f'dedup 需要 datasketch 与 numpy/scipy：pip install "novel-distill[dedup]"（{exc}）',
        ) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise ServiceError("missing", str(exc)) from exc


def vault_links(vault: str | None = None) -> dict:
    from .store import vaultcheck

    try:
        return vaultcheck.check_vault(Path(resolve_vault(vault)))
    except Exception as exc:  # noqa: BLE001 - vault 可能不存在或库缺失
        return {"available": False, "reason": str(exc), "broken_links": [], "orphan_notes": []}


def audit(
    slug: str,
    *,
    vault: str | None = None,
    vault_links: bool = True,
    dedup_enabled: bool = True,
    threshold: float = 0.9,
    min_chars: int = 2000,
    num_perm: int = 128,
) -> dict:
    """一键体检：lint（含双链）+ 近重复检测。"""
    report: dict[str, Any] = {"lint": lint(slug, vault=vault, vault_links=vault_links)}
    if dedup_enabled:
        try:
            report["dedup"] = dedup(slug, threshold=threshold, min_chars=min_chars, num_perm=num_perm)
        except ServiceError as exc:
            report["dedup_error"] = exc.message
    return report


def keywords(slug: str, *, start: int = 1, count: int = 5, top: int = 40) -> dict:
    from .ingest import keywords as kw

    return kw.collect(_book_dir(slug), start=start, count=count, top=top)


def continuity(slug: str, *, upto: int | None = None, recent: int = 12, style_sample: bool = True) -> dict:
    _require_write("生成续写上下文包")
    from .pack.continue_pack import build

    return build(_book_dir(slug), upto=upto, recent=recent, style_sample=style_sample)


def voice(slug: str, *, min_importance: int = 3, limit: int = 12, out: str | None = None, vault: str | None = None) -> dict:
    _require_write("生成人物口吻卡")
    from .render.voice import build

    return build(_book_dir(slug), min_importance=min_importance, limit=limit, out=out, vault=vault)

