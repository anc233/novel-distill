"""CustomTkinter 图形界面（浅色、中英双语、便携）。

设计：
- 5 页：概览（选书 + 统计 + 自检）/ 流程（导入→任务包→校验→写库→渲染）/ 查询 / 审计 / 设置
- 长任务在线程执行，结果经 queue 回主线程刷新（tkinter 不能跨线程改控件）
- 设置写在程序同级目录，数据在工作目录（默认同级 workspace/）
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from tkinter import BooleanVar, StringVar, filedialog, messagebox
from typing import Any

import customtkinter as ctk

try:  # 拖拽是可选能力：没装 tkinterdnd2 时界面照常可用
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - 取决于本机依赖
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]

from .. import __version__, config, service
from . import i18n, mcp_connect
from .settings import load_settings, save_settings

PAD = 12
BORDER = "#d7dee8"
MUTED = "#5b6b7f"


def _fmt(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


GEOMETRY_RE = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")
DEFAULT_WIDTH = 1180
DEFAULT_HEIGHT = 780


def fit_geometry(screen_w: int, screen_h: int, scale: float = 1.0, saved: str = "") -> str:
    """算一个装得下屏幕的 "WxH+X+Y"。

    CTk 会把 geometry() 的宽高乘上窗口缩放系数（位置不乘）；屏幕尺寸是像素，
    所以逻辑宽高必须除 scale，否则 1.25 缩放下 1180 会变成 1475 px 撑出屏幕。
    """
    scale = scale if scale > 0 else 1.0
    match = GEOMETRY_RE.fullmatch(saved.strip())
    if match:
        gw, gh, gx, gy = (int(value) for value in match.groups())
        fits = gw * scale <= screen_w - 20 and gh * scale <= screen_h - 60
        if fits and gx < screen_w - 80 and gy < screen_h - 80:
            return f"{gw}x{gh}+{gx}+{gy}"
    width = min(DEFAULT_WIDTH, max(int((screen_w - 40) / scale), 900))
    height = min(DEFAULT_HEIGHT, max(int((screen_h - 80) / scale), 600))
    x = max((screen_w - int(width * scale)) // 2, 0)
    y = max((screen_h - int(height * scale)) // 3, 0)
    return f"{width}x{height}+{x}+{y}"


def fit_min_size(screen_w: int, screen_h: int, scale: float = 1.0) -> tuple[int, int]:
    scale = scale if scale > 0 else 1.0
    return min(1000, int((screen_w - 20) / scale)), min(660, int((screen_h - 60) / scale))


class App(ctk.CTk):
    def __init__(self, lang: str | None = None, self_test: bool = False) -> None:
        super().__init__()
        self.self_test = self_test
        self.settings = load_settings()
        self.lang = i18n.normalize_lang(lang or self.settings.get("lang"))
        self._queue: queue.Queue[tuple[str, str, Any, Callable | None]] = queue.Queue()
        self._book_map: dict[str, str] = {}
        self._busy = 0
        self._apply_env()
        ctk.set_appearance_mode("light")
        self.title(f"{self.t('app.title')} · novel-distill {__version__}")
        self.geometry(self._initial_geometry())
        self.minsize(*self._min_size())
        self._init_dnd()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._show("overview")
        self.after(100, self._pump)
        self.after(180, self.refresh_books)

    # ---------- 基础设施 ----------

    def t(self, key: str, /, **kwargs: Any) -> str:
        return i18n.t(self.lang, key, **kwargs)

    def _font(self, size: int = 13, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family=self._family, size=size, weight=weight)

    def _pick_font(self) -> str:
        try:
            from tkinter import font as tkfont

            families = set(tkfont.families(self))
        except Exception:  # noqa: BLE001 - Tk 字体查询在无显示环境会抛任意 TclError
            families = set()
        for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial"):
            if name in families:
                return name
        return "TkDefaultFont"

    def _apply_env(self) -> None:
        ws = (self.settings.get("workspace") or "").strip()
        if ws:
            os.environ["NOVEL_DISTILL_WORKSPACE"] = ws
        else:
            os.environ.pop("NOVEL_DISTILL_WORKSPACE", None)
        vault = (self.settings.get("vault") or "").strip()
        if vault:
            os.environ["NOVEL_DISTILL_VAULT"] = vault
        else:
            os.environ.pop("NOVEL_DISTILL_VAULT", None)
        if self.settings.get("readonly"):
            os.environ["NOVEL_DISTILL_READONLY"] = "1"
        else:
            os.environ.pop("NOVEL_DISTILL_READONLY", None)

    def _window_scale(self) -> float:
        """CTk 把 geometry() 的宽高乘上窗口缩放系数（位置不乘），所以要按它换算像素。"""
        try:
            scale = float(ctk.ScalingTracker.get_window_scaling(self))
        except Exception:  # noqa: BLE001 - 老版本没有 ScalingTracker 就按 1 处理
            scale = 1.0
        return scale if scale > 0 else 1.0

    def _initial_geometry(self) -> str:
        return fit_geometry(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            self._window_scale(),
            self.settings.get("geometry") or "",
        )

    def _min_size(self) -> tuple[int, int]:
        return fit_min_size(self.winfo_screenwidth(), self.winfo_screenheight(), self._window_scale())

    def _init_dnd(self) -> None:
        self._dnd = False
        if TkinterDnD is None:
            return
        try:
            self._tkdnd_version = TkinterDnD._require(self)
            self._dnd = True
        except Exception:  # noqa: BLE001 - 缺 tkdnd 二进制时降级为不支持拖拽
            self._dnd = False

    def _drop_target(self, widget: Any) -> None:
        """把 CTk 控件（含其内部 canvas/entry）注册成拖放目标。"""
        if not self._dnd:
            return
        targets = [widget]
        for attr in ("_canvas", "_entry"):
            inner = getattr(widget, attr, None)
            if inner is not None:
                targets.append(inner)
        for target in targets:
            try:
                TkinterDnD.DnDWrapper.drop_target_register(target, DND_FILES)
                TkinterDnD.DnDWrapper.dnd_bind(target, "<<Drop>>", self._on_drop)
            except Exception:  # noqa: BLE001, S112 - 单个控件注册失败不影响其它控件
                continue

    def _on_drop(self, event: Any) -> str:
        try:
            raw = list(self.tk.splitlist(event.data))
        except Exception:  # noqa: BLE001 - 个别客户端给的 data 不是 Tcl 列表
            raw = [str(event.data)]
        files = [p for p in raw if str(p).lower().endswith((".txt", ".md"))]
        if not files:
            self._log(self.t("pipeline.drop_bad"))
            return "break"
        self._show("pipeline")
        self.path_var.set(files[0])
        if not self.title_var.get().strip():
            self.title_var.set(Path(files[0]).stem)
        if len(files) > 1:
            self._log(self.t("pipeline.drop_multi", n=len(files)))
        self.run_import()
        return "break"

    def _save_quiet(self) -> None:
        with contextlib.suppress(OSError):
            save_settings(self.settings)

    def _on_close(self) -> None:
        try:
            self.settings["geometry"] = self.geometry()
            self._save_quiet()
        finally:
            self.destroy()

    # ---------- 布局 ----------

    def _build(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._family = self._pick_font()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=216, corner_radius=0, fg_color="#eef2f7")
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(
            side, text=self.t("app.title"), font=self._font(18, "bold"), anchor="w", text_color="#1f2d3d"
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(20, 0))
        ctk.CTkLabel(
            side,
            text=self.t("app.subtitle"),
            font=self._font(11),
            text_color=MUTED,
            anchor="w",
            wraplength=170,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(2, 16))

        self._nav: dict[str, ctk.CTkButton] = {}
        for i, (name, key) in enumerate(
            [
                ("overview", "nav.overview"),
                ("pipeline", "nav.pipeline"),
                ("query", "nav.query"),
                ("audit", "nav.audit"),
                ("settings", "nav.settings"),
            ]
        ):
            btn = ctk.CTkButton(
                side,
                text=self.t(key),
                anchor="w",
                height=36,
                corner_radius=8,
                fg_color="transparent",
                text_color="#23364a",
                hover_color="#dfe7f1",
                font=self._font(13),
                command=lambda n=name: self._show(n),
            )
            btn.grid(row=2 + i, column=0, sticky="ew", padx=10, pady=2)
            self._nav[name] = btn

        self.sidebar_book = ctk.CTkLabel(
            side, text="", font=self._font(11), text_color=MUTED, anchor="w", wraplength=180, justify="left"
        )
        self.sidebar_book.grid(row=7, column=0, sticky="ew", padx=16, pady=8)
        self.status_label = ctk.CTkLabel(
            side, text="", font=self._font(11), text_color=MUTED, anchor="w", wraplength=180, justify="left"
        )
        self.status_label.grid(row=8, column=0, sticky="ew", padx=16, pady=(0, 14))

        self.content = ctk.CTkFrame(self, fg_color="#f7f9fc", corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._pages: dict[str, ctk.CTkFrame] = {
            "overview": self._page_overview(),
            "pipeline": self._page_pipeline(),
            "query": self._page_query(),
            "audit": self._page_audit(),
            "settings": self._page_settings(),
        }
        for page in self._pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self._highlight(None)

    def _show(self, name: str) -> None:
        self._pages[name].tkraise()
        self._highlight(name)

    def _highlight(self, name: str | None) -> None:
        for key, btn in self._nav.items():
            active = key == name
            btn.configure(fg_color="#dbe6f3" if active else "transparent")

    def _group(self, parent: Any, title: str) -> ctk.CTkFrame:
        """建一个带标题的白卡片，**自己 pack 进 parent**，返回可放控件的内部容器。"""
        frame = ctk.CTkFrame(parent, fg_color="white", border_width=1, border_color=BORDER, corner_radius=10)
        frame.pack(fill="x", padx=PAD, pady=6)
        ctk.CTkLabel(frame, text=title, font=self._font(13, "bold"), anchor="w", text_color="#1f2d3d").pack(
            fill="x", padx=12, pady=(8, 2)
        )
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(0, 10))
        return inner

    def _textbox(self, parent: Any, height: int = 160) -> ctk.CTkTextbox:
        box = ctk.CTkTextbox(
            parent,
            wrap="word",
            height=height,
            font=self._font(12),
            fg_color="white",
            border_width=1,
            border_color=BORDER,
            text_color="#1f2d3d",
        )
        box.configure(state="disabled")
        return box

    def _set_text(self, box: ctk.CTkTextbox, text: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    # ---------- 任务执行 ----------

    def _log(self, text: str) -> None:
        if not hasattr(self, "log_box"):
            return
        stamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start(self, name: str, fn: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        self._log(self.t("common.running", name=name))
        self._busy += 1
        self.status_label.configure(text=self.t("common.running", name=name))

        def worker() -> None:
            try:
                result = fn()
            except service.ServiceError as exc:
                self._queue.put(("err", name, f"[{exc.code}] {exc.message}", None))
            except Exception as exc:  # noqa: BLE001 - GUI 需要兜住任何异常并显示出来
                self._queue.put(("err", name, f"{type(exc).__name__}: {exc}", None))
            else:
                self._queue.put(("ok", name, result, done))

        threading.Thread(target=worker, daemon=True).start()

    def _pump(self) -> None:
        while True:
            try:
                kind, name, payload, done = self._queue.get_nowait()
            except queue.Empty:
                break
            self._busy = max(0, self._busy - 1)
            if kind == "ok":
                self._log(self.t("common.done", name=name))
                if done is not None:
                    try:
                        done(payload)
                    except Exception as exc:  # noqa: BLE001
                        self._log(f"{type(exc).__name__}: {exc}")
            else:
                self._log(self.t("common.failed", name=name))
                self._log(str(payload))
                self._set_text(self.log_box, self._current_text(self.log_box))
        if self._busy == 0:
            self.status_label.configure(text=self.t("overview.ready"))
        self.after(100, self._pump)

    @staticmethod
    def _current_text(box: ctk.CTkTextbox) -> str:
        return box.get("1.0", "end-1c")

    # ---------- 选书 ----------

    def _book_label(self, book: dict) -> str:
        return f"{book.get('title') or book.get('slug')} · {book.get('slug')}"

    def _slug(self) -> str | None:
        label = self.book_box.get().strip()
        slug = self._book_map.get(label)
        if not slug:
            self._log(self.t("common.select_book"))
            return None
        return slug

    def _on_book_change(self) -> None:
        slug = self._book_map.get(self.book_box.get().strip())
        self.sidebar_book.configure(text=slug or "")
        if not slug:
            self._set_text(self.stats_box, self.t("common.no_book"))
            return
        self._start("stats", lambda: service.stats(slug), lambda res: self._set_text(self.stats_box, _fmt(res)))

    def refresh_books(self, select: str | None = None) -> None:
        def done(books: list[dict]) -> None:
            self._book_map = {self._book_label(b): b["slug"] for b in books}
            labels = list(self._book_map)
            self.book_box.configure(values=labels)
            if not labels:
                self.book_box.set("")
                self._set_text(self.stats_box, self.t("common.no_book"))
                self.book_info.configure(text=self.t("overview.books", n=0))
                return
            current = select or self.book_box.get()
            if current not in labels:
                current = labels[0]
            self.book_box.set(current)
            self.book_info.configure(text=self.t("overview.books", n=len(labels)))
            self._on_book_change()

        self._start("list_books", service.list_books, done)

    # ---------- 页 1：概览 ----------

    def _page_overview(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=3)
        page.grid_rowconfigure(4, weight=2)

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 2))
        ctk.CTkLabel(bar, text=f"{self.t('common.book')}:", font=self._font(13, "bold")).pack(side="left")
        self.book_box = ctk.CTkComboBox(bar, values=[], width=330, font=self._font(12), command=lambda _=None: self._on_book_change())
        self.book_box.pack(side="left", padx=8)
        ctk.CTkButton(
            bar, text=self.t("common.refresh"), width=80, font=self._font(12), command=self.refresh_books
        ).pack(side="left")
        self.book_info = ctk.CTkLabel(bar, text="", font=self._font(11), text_color=MUTED)
        self.book_info.pack(side="left", padx=10)
        ctk.CTkButton(
            bar,
            text=self.t("overview.doctor"),
            width=110,
            font=self._font(12),
            command=self.run_doctor,
        ).pack(side="right")

        ctk.CTkLabel(page, text=self.t("overview.stats"), font=self._font(13, "bold"), anchor="w").grid(
            row=1, column=0, sticky="ew", padx=PAD + 2, pady=(6, 2)
        )
        self.stats_box = self._textbox(page, 220)
        self.stats_box.grid(row=2, column=0, sticky="nsew", padx=PAD, pady=(0, 8))

        ctk.CTkLabel(page, text=self.t("overview.doctor"), font=self._font(13, "bold"), anchor="w").grid(
            row=3, column=0, sticky="ew", padx=PAD + 2, pady=(6, 2)
        )
        self.doctor_box = self._textbox(page, 180)
        self.doctor_box.grid(row=4, column=0, sticky="nsew", padx=PAD, pady=(0, PAD))
        return page

    def run_doctor(self) -> None:
        vault = (self.settings.get("vault") or "").strip() or None

        def done(rep: dict) -> None:
            lines = [f"[{'✓' if c['ok'] else '✗'}] {c['name']}: {c['detail']}" for c in rep["checks"]]
            lines.append("")
            lines.append(f"workspace: {rep['workspace']}")
            lines.append(f"vault: {rep['vault']}")
            self._set_text(self.doctor_box, "\n".join(lines))

        self._start("doctor", lambda: service.doctor(vault), done)

    # ---------- 页 2：流程 ----------

    def _page_pipeline(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(4, weight=1)

        top = ctk.CTkFrame(page, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")

        # 导入
        g = self._group(top, self.t("pipeline.add"))
        g.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g, text=self.t("pipeline.path"), font=self._font(12)).grid(row=0, column=0, sticky="w")
        self.path_var = StringVar(value="")
        self.path_entry = ctk.CTkEntry(g, textvariable=self.path_var, font=self._font(12))
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(g, text=self.t("pipeline.browse"), width=84, font=self._font(12), command=self._browse).grid(
            row=0, column=2, padx=2
        )
        ctk.CTkButton(g, text=self.t("pipeline.add"), width=110, font=self._font(12), command=self.run_import).grid(
            row=0, column=3, padx=(6, 0)
        )
        ctk.CTkLabel(g, text=self.t("pipeline.title"), font=self._font(12)).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.title_var = StringVar(value="")
        ctk.CTkEntry(g, textvariable=self.title_var, font=self._font(12)).grid(
            row=1, column=1, sticky="ew", padx=6, pady=(6, 0)
        )

        # 拖拽区：拖 .txt 进来直接导入
        self.drop_zone = ctk.CTkFrame(
            g, fg_color="#f2f7fd", border_width=1, border_color="#b9d1ee", corner_radius=8
        )
        self.drop_zone.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        self.drop_hint = ctk.CTkLabel(
            self.drop_zone, text=self.t("pipeline.drop_hint"), font=self._font(11), text_color=MUTED
        )
        self.drop_hint.pack(padx=8, pady=10)
        for widget in (self.path_entry, self.drop_zone, self.drop_hint):
            self._drop_target(widget)

        # 任务包
        g = self._group(top, self.t("pipeline.packet"))
        self.start_var = StringVar(value="1")
        self.count_var = StringVar(value=str(config.DEFAULT_BATCH_CHAPTERS))
        self.force_var = BooleanVar(value=False)
        ctk.CTkLabel(g, text=self.t("pipeline.start"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.start_var, width=70, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkLabel(g, text=self.t("pipeline.count"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.count_var, width=70, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkCheckBox(g, text=self.t("pipeline.force"), variable=self.force_var, font=self._font(12)).pack(
            side="left", padx=8
        )
        ctk.CTkButton(g, text=self.t("pipeline.packet"), width=120, font=self._font(12), command=self.run_packet).pack(
            side="right"
        )

        # 校验 / 写库 / 渲染
        g = self._group(top, self.t("pipeline.validate"))
        self.batch_var = StringVar(value="b0001")
        ctk.CTkLabel(g, text=self.t("pipeline.batch"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.batch_var, width=110, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkButton(g, text=self.t("pipeline.validate"), width=96, font=self._font(12), command=self.run_validate).pack(
            side="left", padx=4
        )
        self.apply_confirm = BooleanVar(value=False)
        self.dry_run = BooleanVar(value=False)
        self.force_apply = BooleanVar(value=False)
        ctk.CTkCheckBox(g, text=self.t("common.confirm"), variable=self.apply_confirm, font=self._font(12)).pack(
            side="left", padx=(14, 2)
        )
        ctk.CTkCheckBox(g, text=self.t("pipeline.dry_run"), variable=self.dry_run, font=self._font(12)).pack(
            side="left", padx=4
        )
        ctk.CTkCheckBox(g, text=self.t("pipeline.force_apply"), variable=self.force_apply, font=self._font(12)).pack(
            side="left", padx=4
        )
        ctk.CTkButton(g, text=self.t("pipeline.apply"), width=90, font=self._font(12), command=self.run_apply).pack(
            side="left", padx=8
        )

        g = self._group(top, self.t("pipeline.render"))
        self.render_confirm = BooleanVar(value=False)
        self.clean_var = BooleanVar(value=False)
        self.plain_links_var = BooleanVar(value=False)
        ctk.CTkCheckBox(g, text=self.t("common.confirm"), variable=self.render_confirm, font=self._font(12)).pack(
            side="left"
        )
        ctk.CTkCheckBox(g, text=self.t("pipeline.clean"), variable=self.clean_var, font=self._font(12)).pack(
            side="left", padx=8
        )
        ctk.CTkCheckBox(
            g, text=self.t("pipeline.plain_links"), variable=self.plain_links_var, font=self._font(12)
        ).pack(side="left", padx=4)
        ctk.CTkButton(g, text=self.t("pipeline.render"), width=120, font=self._font(12), command=self.run_render).pack(
            side="right"
        )

        ctk.CTkLabel(page, text=self.t("pipeline.log"), font=self._font(13, "bold"), anchor="w").grid(
            row=3, column=0, sticky="ew", padx=PAD + 2, pady=(8, 2)
        )
        self.log_box = self._textbox(page, 200)
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=PAD, pady=(0, PAD))
        return page

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title=self.t("pipeline.add"),
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if path:
            self.path_var.set(path)
            if not self.title_var.get().strip():
                self.title_var.set(Path(path).stem)

    def run_import(self) -> None:
        path = self.path_var.get().strip()
        title = self.title_var.get().strip() or None
        if not path:
            messagebox.showwarning(self.t("app.title"), self.t("pipeline.path"))
            return

        def done(res: dict) -> None:
            if hasattr(self, "stats_box"):
                self._set_text(self.stats_box, _fmt(res))
            self.refresh_books(select=f"{res.get('title')} · {res.get('slug')}")

        self._start("import", lambda: service.import_book(path, title=title, overwrite=False), done)

    def run_packet(self) -> None:
        slug = self._slug()
        if not slug:
            return
        try:
            start = int(self.start_var.get())
            count = int(self.count_var.get())
        except ValueError:
            messagebox.showwarning(self.t("app.title"), self.t("pipeline.start") + "/" + self.t("pipeline.count"))
            return

        def done(res: dict) -> None:
            self._log(_fmt(res))
            batch = res.get("batch") or ""
            if batch:
                self.batch_var.set(str(batch))

        self._start("make_packet", lambda: service.make_packet(slug, start=start, count=count, force=self.force_var.get()), done)

    def run_validate(self) -> None:
        slug = self._slug()
        if not slug:
            return
        batch = self.batch_var.get().strip()
        if not batch:
            messagebox.showwarning(self.t("app.title"), self.t("pipeline.batch"))
            return

        def done(res: dict) -> None:
            self._log(_fmt(res))

        self._start("validate", lambda: service.validate(slug, batch), done)

    def run_apply(self) -> None:
        slug = self._slug()
        if not slug:
            return
        batch = self.batch_var.get().strip()
        dry = self.dry_run.get()
        if not dry and not self.apply_confirm.get():
            messagebox.showwarning(self.t("app.title"), self.t("pipeline.need_confirm"))
            return

        def done(res: dict) -> None:
            self._log(_fmt(res))
            self.refresh_books()

        self._start(
            "apply",
            lambda: service.apply(
                slug, batch, confirm=self.apply_confirm.get(), dry_run=dry, force=self.force_apply.get()
            ),
            done,
        )

    def run_render(self) -> None:
        slug = self._slug()
        if not slug:
            return
        if not self.render_confirm.get():
            messagebox.showwarning(self.t("app.title"), self.t("pipeline.need_confirm"))
            return
        vault = (self.settings.get("vault") or "").strip() or None

        def done(res: dict) -> None:
            self._log(_fmt(res))

        self._start(
            "render",
            lambda: service.render(
                slug,
                vault=vault,
                clean=self.clean_var.get(),
                plain_links=self.plain_links_var.get(),
                confirm=True,
            ),
            done,
        )

    # ---------- 页 3：查询 ----------

    def _page_query(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color="transparent")

        g = self._group(page, self.t("query.entity"))
        self.entity_var = StringVar(value="")
        ctk.CTkLabel(g, text=self.t("query.name"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.entity_var, width=240, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkButton(g, text=self.t("query.entity"), width=96, font=self._font(12), command=self.run_entity).pack(
            side="left", padx=4
        )

        g = self._group(page, self.t("query.type"))
        self.etype_var = StringVar(value="")
        self.etype_box = ctk.CTkComboBox(
            g,
            values=["", "character", "pill", "technique", "world_rule", "artifact", "faction", "dungeon", "arc", "material"],
            width=200,
            font=self._font(12),
        )
        self.etype_box.pack(side="left")
        self.limit_var = StringVar(value="100")
        ctk.CTkLabel(g, text=self.t("query.limit"), font=self._font(12)).pack(side="left", padx=(10, 0))
        ctk.CTkEntry(g, textvariable=self.limit_var, width=70, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkButton(g, text=self.t("query.type"), width=120, font=self._font(12), command=self.run_entities).pack(
            side="left", padx=4
        )

        g = self._group(page, self.t("query.search"))
        self.kw_var = StringVar(value="")
        ctk.CTkLabel(g, text=self.t("query.keyword"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.kw_var, width=240, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkButton(g, text=self.t("query.search"), width=120, font=self._font(12), command=self.run_search).pack(
            side="left", padx=4
        )

        self.query_box = self._textbox(page, 300)
        self.query_box.pack(fill="both", expand=True, padx=PAD, pady=(6, PAD))
        return page

    def run_entity(self) -> None:
        slug = self._slug()
        if not slug:
            return
        name = self.entity_var.get().strip()
        if not name:
            return
        self._start("query_entity", lambda: service.entity(slug, name), lambda res: self._set_text(self.query_box, _fmt(res)))

    def run_entities(self) -> None:
        slug = self._slug()
        if not slug:
            return
        etype = self.etype_box.get().strip() or None
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 100
        self._start(
            "list_entities",
            lambda: service.entities(slug, etype=etype, limit=limit),
            lambda res: self._set_text(self.query_box, _fmt(res)),
        )

    def run_search(self) -> None:
        slug = self._slug()
        if not slug:
            return
        query = self.kw_var.get().strip()
        if not query:
            return
        self._start("search", lambda: service.search(slug, query, limit=20), lambda res: self._set_text(self.query_box, _fmt(res)))

    # ---------- 页 4：审计 ----------

    def _page_audit(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color="transparent")

        g = self._group(page, self.t("audit.run"))
        self.threshold_var = StringVar(value="0.9")
        self.minchars_var = StringVar(value="2000")
        self.numperm_var = StringVar(value="128")
        ctk.CTkLabel(g, text=self.t("audit.threshold"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.threshold_var, width=70, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkLabel(g, text=self.t("audit.min_chars"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.minchars_var, width=80, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkLabel(g, text=self.t("audit.num_perm"), font=self._font(12)).pack(side="left")
        ctk.CTkEntry(g, textvariable=self.numperm_var, width=70, font=self._font(12)).pack(side="left", padx=6)
        ctk.CTkButton(g, text=self.t("audit.run"), width=110, font=self._font(12), command=self.run_audit).pack(
            side="right"
        )

        self.audit_box = self._textbox(page, 400)
        self.audit_box.pack(fill="both", expand=True, padx=PAD, pady=(4, PAD))
        return page

    def run_audit(self) -> None:
        slug = self._slug()
        if not slug:
            return
        try:
            threshold = float(self.threshold_var.get())
            min_chars = int(self.minchars_var.get())
            num_perm = int(self.numperm_var.get())
        except ValueError:
            messagebox.showwarning(self.t("app.title"), self.t("audit.run"))
            return
        vault = (self.settings.get("vault") or "").strip() or None

        def done(res: dict) -> None:
            self._set_text(self.audit_box, _fmt(res))

        self._start(
            "audit",
            lambda: service.audit(
                slug, vault=vault, threshold=threshold, min_chars=min_chars, num_perm=num_perm
            ),
            done,
        )

    # ---------- 页 5：设置 ----------

    def _page_settings(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color="transparent")

        g = self._group(page, self.t("nav.settings"))
        g.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g, text=self.t("settings.workspace"), font=self._font(12)).grid(row=0, column=0, sticky="w")
        self.ws_var = StringVar(value=self.settings.get("workspace") or "")
        ctk.CTkEntry(g, textvariable=self.ws_var, font=self._font(12)).grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(g, text=self.t("pipeline.browse"), width=84, font=self._font(12), command=self._pick_dir).grid(
            row=0, column=2
        )

        ctk.CTkLabel(g, text=self.t("settings.vault"), font=self._font(12)).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.vault_var = StringVar(value=self.settings.get("vault") or "")
        ctk.CTkEntry(g, textvariable=self.vault_var, font=self._font(12)).grid(
            row=1, column=1, sticky="ew", padx=6, pady=(6, 0)
        )
        ctk.CTkButton(g, text=self.t("pipeline.browse"), width=84, font=self._font(12), command=self._pick_vault).grid(
            row=1, column=2, pady=(6, 0)
        )

        ctk.CTkLabel(g, text=self.t("settings.lang"), font=self._font(12)).grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        self.lang_menu = ctk.CTkOptionMenu(
            g, values=["中文", "English"], width=140, font=self._font(12), command=self._set_lang
        )
        self.lang_menu.set("中文" if self.lang == "zh" else "English")
        self.lang_menu.grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        self.readonly_var = BooleanVar(value=bool(self.settings.get("readonly")))
        ctk.CTkCheckBox(g, text=self.t("settings.readonly"), variable=self.readonly_var, font=self._font(12)).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        actions = ctk.CTkFrame(g, fg_color="transparent")
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ctk.CTkButton(actions, text=self.t("settings.save"), width=110, font=self._font(12), command=self._save).pack(
            side="left"
        )
        ctk.CTkLabel(actions, text=self.t("settings.restart_hint"), font=self._font(11), text_color=MUTED).pack(
            side="left", padx=10
        )

        ctk.CTkLabel(page, text=self.t("settings.mcp"), font=self._font(13, "bold"), anchor="w").pack(
            fill="x", padx=PAD + 2, pady=(8, 2)
        )
        self.mcp_box = self._textbox(page, 150)
        self.mcp_box.pack(fill="both", expand=True, padx=PAD)
        self._set_text(self.mcp_box, self._mcp_snippet())
        mcp_actions = ctk.CTkFrame(page, fg_color="transparent")
        mcp_actions.pack(anchor="w", padx=PAD, pady=4)
        ctk.CTkButton(
            mcp_actions, text=self.t("common.copy"), width=90, font=self._font(12), command=self._copy_mcp
        ).pack(side="left")
        ctk.CTkButton(
            mcp_actions,
            text=self.t("settings.mcp_connect"),
            width=150,
            font=self._font(12),
            command=self._connect_mcp,
        ).pack(side="left", padx=8)
        ctk.CTkLabel(
            mcp_actions, text=self.t("settings.mcp_connect_hint"), font=self._font(11), text_color=MUTED
        ).pack(side="left")

        ctk.CTkLabel(
            page,
            text=self.t("settings.about", version=__version__),
            font=self._font(11),
            text_color=MUTED,
            anchor="w",
        ).pack(anchor="sw", padx=PAD + 2, pady=(4, PAD))
        return page

    def _pick_dir(self) -> None:
        path = filedialog.askdirectory(title=self.t("settings.workspace"))
        if path:
            self.ws_var.set(path)

    def _pick_vault(self) -> None:
        path = filedialog.askdirectory(title=self.t("settings.vault"))
        if path:
            self.vault_var.set(path)

    def _set_lang(self, value: str) -> None:
        lang = "en" if value.lower().startswith("english") or value.lower().startswith("en") else "zh"
        if lang == self.lang:
            return
        self.lang = lang
        self.settings["lang"] = lang
        self._save_quiet()
        self._build()
        self._show("settings")
        self.refresh_books()

    def _save(self) -> None:
        self.settings["workspace"] = self.ws_var.get().strip()
        self.settings["vault"] = self.vault_var.get().strip()
        self.settings["readonly"] = bool(self.readonly_var.get())
        self.settings["lang"] = self.lang
        self.settings["geometry"] = self.geometry()
        path = save_settings(self.settings)
        self._apply_env()
        messagebox.showinfo(self.t("app.title"), self.t("settings.saved", path=str(path)))
        self.refresh_books()

    def _mcp_server_spec(self) -> dict[str, Any]:
        """MCP 客户端里 novel-distill 那条配置（frozen 时用 exe 自己当 command）。"""
        server: dict[str, Any] = {
            "command": sys.executable,
            "args": ["mcp"] if config.FROZEN else ["-m", "novel_distill", "mcp"],
        }
        env: dict[str, str] = {}
        ws = (self.settings.get("workspace") or "").strip()
        if ws:
            env["NOVEL_DISTILL_WORKSPACE"] = ws
        vault = (self.settings.get("vault") or "").strip()
        if vault:
            env["NOVEL_DISTILL_VAULT"] = vault
        if env:
            server["env"] = env
        return server

    def _mcp_snippet(self) -> str:
        server = self._mcp_server_spec()
        return json.dumps({"mcpServers": {"novel-distill": server}}, ensure_ascii=False, indent=2)

    def _copy_mcp(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._mcp_snippet())
        self._log(self.t("common.copied"))

    def _connect_mcp(self) -> None:
        spec = self._mcp_server_spec()
        targets = mcp_connect.detect_targets(config.REPO_ROOT)
        listing = "\n".join(f"· {t['name']} → {t['path']}" for t in targets)
        if not messagebox.askyesno(
            self.t("settings.mcp_connect"), self.t("settings.mcp_connect_body", list=listing)
        ):
            return
        results = mcp_connect.apply(targets, spec)
        messagebox.showinfo(self.t("settings.mcp_connect"), "\n".join(results))
        self._log("\n".join(results))


def main(self_test: bool = False, lang: str | None = None) -> int:
    """启动 GUI；self_test 只构建并销毁，用于打包后的冒烟验证。"""
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    app = App(lang=lang, self_test=self_test)
    if self_test:
        app.update_idletasks()
        app.update()
        for name in ("pipeline", "query", "audit", "settings", "overview"):
            app._show(name)
            app.update_idletasks()
        if app.self_test:
            tkdnd = getattr(app, "_tkdnd_version", "")
            drag = f"yes ({tkdnd})" if app._dnd else "no"
            print(f"gui self-test ok; drag-drop={drag}", flush=True)
        app.destroy()
        return 0
    app.mainloop()
    return 0
