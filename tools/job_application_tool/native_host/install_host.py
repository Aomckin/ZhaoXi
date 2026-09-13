"""Explicit current-user installer for Chrome and Edge Native Messaging."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


HOST_NAME = "com.zhaoxi.job_application"
BROWSER_KEYS = {
    "chrome": rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
    "edge": rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
}


def validate_extension_id(extension_id: str) -> str:
    normalized = extension_id.strip().lower()
    if not re.fullmatch(r"[a-p]{32}", normalized):
        raise ValueError("extension id must be 32 lowercase letters from a-p")
    return normalized


def browser_installed(browser: str) -> bool:
    if os.name != "nt":
        return False
    candidates = {
        "chrome": [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ],
        "edge": [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        ],
    }
    return any(path.is_file() for path in candidates[browser])


def manifest_payload(extension_id: str, launcher: Path) -> dict[str, object]:
    extension_id = validate_extension_id(extension_id)
    return {
        "name": HOST_NAME,
        "description": "Zhaoxi Job Application Browser Bridge",
        "path": str(launcher.resolve()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }


def install(extension_id: str, browsers: list[str]) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("Native Host installation currently supports Windows only.")
    import winreg

    extension_id = validate_extension_id(extension_id)
    package_dir = Path(__file__).resolve().parents[1]
    workspace = package_dir.parents[1]
    generated = package_dir / ".native_host"
    generated.mkdir(exist_ok=True)
    launcher = generated / "job_application_native_host.cmd"
    launcher.write_text(
        "@echo off\r\n"
        f'cd /d "{workspace}"\r\n'
        f'"{Path(sys.executable).resolve()}" -m tools.job_application_tool.native_host.host\r\n',
        encoding="utf-8",
    )
    manifest = generated / f"{HOST_NAME}.json"
    manifest.write_text(
        json.dumps(manifest_payload(extension_id, launcher), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    installed = []
    unavailable = []
    for browser in browsers:
        if not browser_installed(browser):
            unavailable.append(browser)
            continue
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, BROWSER_KEYS[browser]) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
        installed.append(browser)
    return {"manifest": str(manifest), "installed": installed, "not_detected": unavailable}


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the Zhaoxi JobApplication Native Messaging Host")
    parser.add_argument("--extension-id", default=os.environ.get("ZHAOXI_BROWSER_EXTENSION_ID"))
    parser.add_argument("--browser", choices=["chrome", "edge", "both"], default="both")
    args = parser.parse_args()
    if not args.extension_id:
        parser.error("--extension-id is required (or set ZHAOXI_BROWSER_EXTENSION_ID)")
    browsers = ["chrome", "edge"] if args.browser == "both" else [args.browser]
    print(json.dumps(install(args.extension_id, browsers), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
