from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_release_scripts_preserve_user_data_and_require_explicit_autostart():
    install = (ROOT / "scripts" / "install_windows.ps1").read_text(encoding="utf-8")
    uninstall = (ROOT / "scripts" / "uninstall_windows.ps1").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")

    assert "[switch]$EnableAutoStart" in install
    assert "HKCU:" in install and "HKLM:" not in install
    assert "Remove-ItemProperty" in uninstall
    assert "Remove-Item -Recurse" not in uninstall
    assert ".zhaoxi" in uninstall and "preserved" in uninstall
    assert "-m pytest" in build
    assert "-m pip wheel" in build
    assert "SHA256" in build
