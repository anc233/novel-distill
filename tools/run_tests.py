"""零依赖测试运行器：python tools/run_tests.py [名称过滤]

发现 tests/test_*.py 中所有 test_* 函数并执行；支持可选的 tmp_path 夹具。
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def load_module(path: Path):
    name = "t_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> int:
    needle = argv[1] if len(argv) > 1 else ""
    sys.path.insert(0, str(ROOT))
    files = sorted(TESTS.glob("test_*.py"))
    total = failed = skipped = 0
    failures: list[str] = []
    tmp_root = ROOT / ".tmp" / f"run-{os.getpid()}"
    tmp_root.mkdir(parents=True, exist_ok=True)
    case_seq = 0
    try:
        for path in files:
            mod = load_module(path)
            for fname, fn in sorted(vars(mod).items()):
                if not fname.startswith("test_") or not callable(fn):
                    continue
                label = f"{path.stem}::{fname}"
                if needle and needle not in label:
                    skipped += 1
                    continue
                total += 1
                params = inspect.signature(fn).parameters
                kwargs = {}
                case_dir = None
                if "tmp_path" in params:
                    case_seq += 1
                    case_dir = tmp_root / f"case{case_seq}"
                    case_dir.mkdir(parents=True, exist_ok=True)
                    kwargs["tmp_path"] = case_dir
                try:
                    fn(**kwargs)
                    print(f"  ok   {label}")
                except Exception:
                    failed += 1
                    failures.append(label + "\n" + traceback.format_exc())
                    print(f"  FAIL {label}")
                    if case_dir is not None:
                        print(f"       用例目录保留：{case_dir}")
    finally:
        if failed == 0:
            shutil.rmtree(tmp_root, ignore_errors=True)
    print()
    for f in failures:
        print("-" * 70)
        print(f)
    print(f"共 {total} 个用例，失败 {failed}，跳过 {skipped}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
