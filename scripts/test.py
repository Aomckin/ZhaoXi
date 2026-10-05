"""Run offline regression suites, failing if a required runtime is unavailable."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def commands(suite: str) -> list[tuple[str, list[str]]]:
    result = []
    if suite in {"all", "core"}:
        result.append(("Core Python", [sys.executable, "-m", "pytest", "tests"]))
    if suite in {"all", "tools"}:
        for package, tests in [
            ("lifehud", "tools/lifehud_tool/tests"),
            ("career", "tools/career/test"),
            ("mcp", "tools/mcp/tests"),
            ("markitdown", "tools/markitdown/test_package.py"),
        ]:
            result.append((f"Tool Python: {package}", [sys.executable, "-m", "pytest", tests]))
    if suite in {"all", "tools", "web"}:
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required for the selected test suite")
        if suite in {"all", "web"}:
            files = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests/web").glob("*.test.cjs"))
            if not files:
                raise RuntimeError("No frontend tests found")
            result.append(("Web Node", [node, "--test", *files]))
        if suite in {"all", "tools"}:
            for script in ["smoke-test.js", "career-api-test.js"]:
                result.append((f"Career Node: {script}", [node, f"tools/career/test/{script}"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", "core", "tools", "web"], default="all")
    args = parser.parse_args()
    try:
        selected = commands(args.suite)
    except RuntimeError as exc:
        parser.error(str(exc))
    failed = []
    for name, command in selected:
        print(f"\n== {name} ==", flush=True)
        started = time.monotonic()
        code = subprocess.run(command, cwd=ROOT, check=False).returncode
        print(f"{name}: exit={code}, {time.monotonic() - started:.1f}s", flush=True)
        if code:
            failed.append(name)
    print("\n" + ("Failed: " + ", ".join(failed) if failed else "All selected suites passed."))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
