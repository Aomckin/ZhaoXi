"""Remove current-user Chrome/Edge Native Messaging registrations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tools.job_application_tool.native_host.install_host import BROWSER_KEYS


def uninstall(browsers: list[str]) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("Native Host uninstallation currently supports Windows only.")
    import winreg

    removed = []
    missing = []
    for browser in browsers:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, BROWSER_KEYS[browser])
            removed.append(browser)
        except FileNotFoundError:
            missing.append(browser)
    generated = Path(__file__).resolve().parents[1] / ".native_host"
    for filename in ("com.zhaoxi.job_application.json", "job_application_native_host.cmd"):
        path = generated / filename
        if path.is_file():
            path.unlink()
    try:
        generated.rmdir()
    except (FileNotFoundError, OSError):
        pass
    return {"removed": removed, "not_registered": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description="Uninstall the Zhaoxi JobApplication Native Messaging Host")
    parser.add_argument("--browser", choices=["chrome", "edge", "both"], default="both")
    args = parser.parse_args()
    browsers = ["chrome", "edge"] if args.browser == "both" else [args.browser]
    print(json.dumps(uninstall(browsers), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
