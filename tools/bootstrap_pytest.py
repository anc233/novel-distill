"""把 pytest（纯 Python wheel）下载并解包到 .pylibs，绕开 pip 在本机沙箱下的解包限制。

用法：
    python tools/bootstrap_pytest.py
    $env:PYTHONPATH = "$PWD\.pylibs"; python -m pytest -q
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / ".pylibs"
PYPI = "https://pypi.org/pypi/{name}/json"
MARKER_SKIP = ("extra ==", "extra==", "sys_platform", "os_name", "python_version <")


def fetch_json(name: str) -> dict:
    with urllib.request.urlopen(PYPI.format(name=name), timeout=30) as fh:
        return json.load(fh)


def pick_wheel(meta: dict) -> str:
    urls = meta["urls"]
    wheels = [u for u in urls if u["filename"].endswith(".whl") and "py3-none-any" in u["filename"]]
    if not wheels:
        wheels = [u for u in urls if u["filename"].endswith(".whl") and "none-any" in u["filename"]]
    if not wheels:
        raise SystemExit(f"[x] {meta['info']['name']} 没有纯 Python wheel")
    wheels.sort(key=lambda u: u["filename"])
    return wheels[-1]["url"]


def req_names(metadata: str) -> list[str]:
    out: list[str] = []
    for line in metadata.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        spec = line.split(":", 1)[1].strip()
        if any(skip in spec for skip in MARKER_SKIP):
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)", spec.split(";")[0].strip())
        if m:
            out.append(m.group(1))
    return out


def installed(name: str) -> bool:
    norm = name.lower().replace("-", "_")
    return any((LIBS / p).exists() for p in {norm, norm + ".py"})


def install(name: str, seen: set[str]) -> None:
    key = name.lower().replace("_", "-")
    if key in seen:
        return
    seen.add(key)
    if installed(name):
        print(f"  = {name} 已存在")
        dep_metadata = read_metadata(name)
        for dep in req_names(dep_metadata):
            install(dep, seen)
        return
    meta = fetch_json(name)
    wheel_url = pick_wheel(meta)
    version = meta["info"]["version"]
    LIBS.mkdir(parents=True, exist_ok=True)
    tmp = LIBS / f".{key}-{version}.whl"
    print(f"  ↓ {name}=={version}")
    urllib.request.urlretrieve(wheel_url, tmp)
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(LIBS)
    tmp.unlink(missing_ok=True)
    metadata = ""
    for dist in LIBS.glob("*.dist-info"):
        if dist.name.lower().startswith(key.replace("-", "_")):
            mf = dist / "METADATA"
            if mf.exists():
                metadata = mf.read_text(encoding="utf-8", errors="replace")
    for dep in req_names(metadata):
        install(dep, seen)


def read_metadata(name: str) -> str:
    key = name.lower().replace("-", "_")
    for dist in LIBS.glob("*.dist-info"):
        if dist.name.lower().startswith(key):
            mf = dist / "METADATA"
            if mf.exists():
                return mf.read_text(encoding="utf-8", errors="replace")
    return ""


def main() -> int:
    print(f"[i] 目标目录 {LIBS}")
    install("pytest", set())
    sys.path.insert(0, str(LIBS))
    import pytest  # noqa: F401

    print(f"[ok] pytest {pytest.__version__} → {LIBS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
