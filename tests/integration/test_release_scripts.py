from pathlib import Path
import tomllib

import zhaoxi


ROOT = Path(__file__).parents[2]


def test_release_scripts_preserve_user_data_and_require_explicit_autostart():
    install = (ROOT / "scripts" / "install_windows.ps1").read_text(encoding="utf-8")
    uninstall = (ROOT / "scripts" / "uninstall_windows.ps1").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify_release.py").read_text(encoding="utf-8")

    assert "[switch]$EnableAutoStart" in install
    assert "HKCU:" in install and "HKLM:" not in install
    assert "Remove-ItemProperty" in uninstall
    assert "Remove-Item -Recurse" not in uninstall
    assert ".zhaoxi" in uninstall and "preserved" in uninstall
    assert "-m pytest" in build
    assert "-m pip wheel" in build
    assert "verify_release.py" in build
    assert "pip install --no-deps --target" in build
    assert "SHA256SUMS.json" in verifier
    assert "FORBIDDEN_SUFFIXES" in verifier


def test_source_and_package_versions_match():
    root = Path(__file__).parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == zhaoxi.__version__
    tool = tomllib.loads(
        (root / "tools" / "lifehud_tool" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["version"] == "1.1.0"
    assert tool["project"]["version"] == "1.0.0"
