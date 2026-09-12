"""Install the Windows Native Messaging manifest for the current user.

This helper is intentionally not run during package import. Installation is an
explicit user action because it writes a launcher and a per-user registry key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


HOST_NAME = "com.zhaoxi.job_application"


def install_windows(extension_id: str) -> Path:
    if os.name != "nt":
        raise RuntimeError("This installer currently supports Windows only.")
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        raise ValueError("extension id must be 32 lowercase letters from a-p")
    import winreg

    package_dir = Path(__file__).resolve().parent
    workspace = package_dir.parents[1]
    generated = package_dir / ".native_host"
    generated.mkdir(exist_ok=True)
    launcher = generated / "job_application_native_host.cmd"
    launcher.write_text(
        "@echo off\r\n"
        f'cd /d "{workspace}"\r\n'
        f'"{Path(sys.executable).resolve()}" -m tools.job_application_tool.native_host\r\n',
        encoding="utf-8",
    )
    manifest = generated / f"{HOST_NAME}.json"
    manifest.write_text(json.dumps({
        "name": HOST_NAME,
        "description": "Zhaoxi JobApplication Native Messaging Host",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extension-id", required=True)
    args = parser.parse_args()
    print(install_windows(args.extension_id))


if __name__ == "__main__":
    main()
