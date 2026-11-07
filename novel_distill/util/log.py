from __future__ import annotations

import sys


def _ensure_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001, S110 - 某些终端流不支持 reconfigure
        pass


def info(msg: str) -> None:
    _ensure_utf8()
    print(msg, flush=True)


def warn(msg: str) -> None:
    _ensure_utf8()
    print(f"[warn] {msg}", file=sys.stderr, flush=True)


def error(msg: str) -> None:
    _ensure_utf8()
    print(f"[error] {msg}", file=sys.stderr, flush=True)
