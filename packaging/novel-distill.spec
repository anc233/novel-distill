# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（PyInstaller 6.x）。

用法（仓库根目录）：
    python -m PyInstaller packaging/novel-distill.spec --noconfirm

产物是 dist/novel-distill/ 目录（onedir），整个目录压 zip 发给别人即可。
不写死任何本机路径：仓库根由 SPECPATH 推出，打包入口是 packaging/launcher.py。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent  # packaging/ 的父目录 = 仓库根
PKG = ROOT / "novel_distill"


def _collect(name):
    """尽力收集可选依赖的数据文件/二进制；没装就跳过，不中断打包。"""
    try:
        return collect_all(name)
    except Exception:  # noqa: BLE001 - 可选依赖缺失属正常情况
        return [], [], []


datas = [(str(PKG / "store" / "schema.sql"), "novel_distill/store")]
binaries = []
hiddenimports = [
    "novel_distill.gui",
    "novel_distill.mcp_server",
    "novel_distill.store.schema",
]

for _mod in ("customtkinter", "tkinterdnd2", "jieba"):
    _d, _b, _h = _collect(_mod)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "PIL",
        "IPython",
        "pytest",
        "setuptools",
        "pip",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="novel-distill",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 保留控制台：同一份 exe 既是 GUI 也是命令行
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="novel-distill",
)
