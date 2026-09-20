#!/usr/bin/env python3
"""Check the pinned runtime dependencies; install only with explicit --install."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQ_FILE = ROOT / "requirements.txt"
PYTHON_REQUIRED = (3, 14, 7)
GIT_PACKAGE_VERSIONS = {"chanlun": "2606.73"}


def read_requirements() -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in REQ_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if match:
            requirements[match.group(1)] = match.group(2)
            continue
        direct = re.fullmatch(
            r"([A-Za-z0-9_.-]+)\s*@\s*(git\+https://\S+)", line
        )
        if direct:
            distribution = direct.group(1)
            requirements[distribution] = GIT_PACKAGE_VERSIONS.get(distribution, "")
            continue
        raise ValueError(f"不支持的依赖格式: {line}")
    return requirements


def check() -> dict:
    requirements = read_requirements()
    py_actual = ".".join(map(str, sys.version_info[:3]))
    result = {
        "有效": True,
        "python": {"required": ".".join(map(str, PYTHON_REQUIRED)), "actual": py_actual,
                   "ok": sys.version_info[:3] == PYTHON_REQUIRED},
        "packages": {}, "imports": {}, "errors": [], "warnings": [],
    }
    if not result["python"]["ok"]:
        result["warnings"].append("Python 版本与固定基线不一致")
    import_names = {"chanlun": "chanlun", "eltdx": "eltdx", "PyYAML": "yaml"}
    for distribution, required in requirements.items():
        try:
            actual = metadata.version(distribution)
            ok = actual == required
        except metadata.PackageNotFoundError:
            actual, ok = None, False
        result["packages"][distribution] = {"required": required, "actual": actual, "ok": ok}
        if not ok:
            result["errors"].append(f"{distribution}: 需要 {required}，实际 {actual or '未安装'}")
        module = import_names.get(distribution)
        if module:
            try:
                importlib.import_module(module)
                result["imports"][module] = {"ok": True}
            except BaseException as exc:
                result["imports"][module] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                result["errors"].append(f"导入 {module} 失败")
    result["有效"] = not result["errors"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 chanlun-skill 固定依赖")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--install", action="store_true", help="显式调用 pip 安装固定依赖")
    args = parser.parse_args()
    result = check()
    if args.install and not result["有效"]:
        completed = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQ_FILE)], check=False)
        if completed.returncode:
            result["errors"].append(f"pip 安装失败，退出码 {completed.returncode}")
        else:
            result = check()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"依赖自检: {'通过' if result['有效'] else '失败'}")
        for error in result["errors"]:
            print(f"- {error}")
        for warning in result["warnings"]:
            print(f"警告: {warning}")
    return 0 if result["有效"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
