"""pytest 启动时的一次性兼容层（只在真的有问题的机器上生效）。

背景：Python 3.14 在 Windows 上用 os.mkdir(path, 0o700) 建目录时，会写出
"受保护 DACL + Low 完整性标签"，连创建者自己都无法往里写文件。pytest 的
tmp_path（_pytest/tmpdir.py 里 path.mkdir(mode=0o700)）、tempfile.mkdtemp()
以及 pip 的 pip-unpack-* 全部踩这条路径，表现为：

    PermissionError: [Errno 13] Permission denied: '...'

所以本文件启动时先探测一次；只有确实命中才把 mkdir 改回默认（不带 mode）的
写法，健康机器上不做任何修改。
"""

from __future__ import annotations

import os
import pathlib
import secrets
import shutil
import sys
import tempfile

_APPLIED = False


def _dir_writable(path: str) -> bool:
    probe = os.path.join(path, ".write-probe")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"1")
        os.unlink(probe)
        return True
    except OSError:
        return False


def _acl_broken() -> bool:
    """True = 本机 mkdir(mode=0o700) 产出的目录不可写。"""
    try:
        probe = tempfile.mkdtemp(prefix=".acl-probe-")
    except OSError:
        return True
    try:
        return not _dir_writable(probe)
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def _patch() -> None:
    global _APPLIED
    if _APPLIED:
        return

    def mkdtemp(suffix=None, prefix=None, dir=None):
        suffix = "" if suffix is None else suffix
        prefix = "tmp" if prefix is None else prefix
        base = dir or tempfile.gettempdir()
        for _ in range(10_000):
            candidate = os.path.join(base, f"{prefix}{secrets.token_hex(5)}{suffix}")
            try:
                os.mkdir(candidate)  # 关键：不传 mode
                return candidate
            except FileExistsError:
                continue
        raise FileExistsError(f"无法在 {base} 下创建临时目录")

    tempfile.mkdtemp = mkdtemp

    real_mkdir = pathlib.Path.mkdir

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        return real_mkdir(self, 0o777, parents, exist_ok)

    pathlib.Path.mkdir = mkdir
    _APPLIED = True


if sys.platform == "win32" and sys.version_info >= (3, 14) and _acl_broken():
    _patch()
