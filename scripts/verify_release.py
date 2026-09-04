"""Fail the release when versions, wheels, hashes, or package contents drift."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile


FORBIDDEN_SUFFIXES = (".env", ".db", ".sqlite", ".log", ".wav", ".mp3", ".pyc")


def _metadata_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        forbidden = [
            name for name in archive.namelist()
            if name.lower().endswith(FORBIDDEN_SUFFIXES)
            or "/.zhaoxi/" in name.lower()
            or "/__pycache__/" in name.lower()
        ]
        if forbidden:
            raise RuntimeError(f"wheel 包含禁止的用户数据或秘密文件：{forbidden}")
    for line in metadata.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise RuntimeError(f"wheel 缺少 Version metadata：{wheel.name}")


def verify(root: Path, dist: Path) -> dict[str, object]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    core_version = project["project"]["version"]
    tool_project = tomllib.loads(
        (root / "tools" / "lifehud_tool" / "pyproject.toml").read_text(encoding="utf-8")
    )
    tool_version = tool_project["project"]["version"]
    source = (root / "src" / "zhaoxi" / "__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{core_version}"' not in source:
        raise RuntimeError("pyproject.toml 与源码版本不一致")
    if core_version != "1.1.0" or tool_version != "1.0.0":
        raise RuntimeError("正式构建要求 Core 为 1.1.0，LifeHUD-Tool 为 1.0.0")

    core_wheels = sorted(dist.glob(f"zhaoxi-{core_version}-*.whl"))
    tool_wheels = sorted(dist.glob(f"zhaoxi_lifehud_tool-{tool_version}-*.whl"))
    if len(core_wheels) != 1 or len(tool_wheels) != 1:
        raise RuntimeError("发布目录必须且只能包含一个当前版本的 Core 与 LifeHUD-Tool wheel")
    wheels = core_wheels + tool_wheels
    for wheel, expected in ((core_wheels[0], core_version), (tool_wheels[0], tool_version)):
        if _metadata_version(wheel) != expected:
            raise RuntimeError(f"wheel metadata 版本不一致：{wheel.name}")

    hashes = [{"Hash": hashlib.sha256(path.read_bytes()).hexdigest().upper(), "Path": path.name}
              for path in wheels]
    checksum_path = dist / "SHA256SUMS.json"
    checksum_path.write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"version": core_version, "wheels": [path.name for path in wheels], "hashes": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = args.root.resolve()
    dist = args.dist if args.dist.is_absolute() else root / args.dist
    print(json.dumps(verify(root, dist), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
