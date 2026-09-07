import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tomllib
import zipfile

import pytest
import zhaoxi
from tools.lifehud_tool.package import LifeHudToolPackage

ROOT = Path(__file__).parents[2]
verify = runpy.run_path(str(ROOT / "scripts/verify_release.py"))["verify"]


def test_source_and_package_versions_match():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = tomllib.loads((ROOT / "tools/lifehud_tool/pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == zhaoxi.__version__
    assert tool["project"]["version"] == LifeHudToolPackage.package_version


@pytest.fixture
def release(tmp_path):
    (tmp_path / "tools/lifehud_tool").mkdir(parents=True)
    (tmp_path / "src/zhaoxi").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "2.3.4"\n')
    (tmp_path / "tools/lifehud_tool/pyproject.toml").write_text('[project]\nversion = "5.6.7"\n')
    (tmp_path / "src/zhaoxi/__init__.py").write_text('__version__ = "2.3.4"\n')
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, version in [("zhaoxi", "2.3.4"), ("zhaoxi_lifehud_tool", "5.6.7")]:
        with zipfile.ZipFile(dist / f"{name}-{version}-py3-none-any.whl", "w") as wheel:
            wheel.writestr(f"{name}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n")
    return tmp_path, dist


def test_release_verifies_independent_versions_and_writes_hashes(release):
    root, dist = release
    result = verify(root, dist)
    assert result["version"] == "2.3.4"
    expected = [{"Path": p.name, "Hash": hashlib.sha256(p.read_bytes()).hexdigest().upper()}
                for p in sorted(dist.glob("*.whl"))]
    assert result["hashes"] == expected
    assert json.loads((dist / "SHA256SUMS.json").read_text()) == expected


@pytest.mark.parametrize("fault, message", [
    ("source", "源码版本"), ("metadata", "metadata 版本"),
    ("missing", "只能包含一个"), ("duplicate", "只能包含一个"),
    ("secret", "禁止"), ("database", "禁止"),
])
def test_release_rejects_invalid_artifacts(release, fault, message):
    root, dist = release
    wheel = dist / "zhaoxi-2.3.4-py3-none-any.whl"
    if fault == "source":
        (root / "src/zhaoxi/__init__.py").write_text('__version__ = "0.0.0"')
    elif fault == "missing":
        wheel.unlink()
    elif fault == "duplicate":
        shutil.copyfile(wheel, dist / "zhaoxi-2.3.4-py2-none-any.whl")
    elif fault == "metadata":
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("zhaoxi-2.3.4.dist-info/METADATA", "Version: 0.0.0")
    else:
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("zhaoxi/.env" if fault == "secret" else "zhaoxi/user.db", "private")
    with pytest.raises(RuntimeError, match=message):
        verify(root, dist)
    assert not (dist / "SHA256SUMS.json").exists()


@pytest.mark.parametrize("operation", ["install", "autostart", "uninstall"])
def test_windows_installation_preserves_data_and_autostart_is_opt_in(tmp_path, operation):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell is required for Windows installer tests")
    data = tmp_path / ".zhaoxi"
    data.mkdir()
    sentinel = data / "memory.db"
    sentinel.write_bytes(b"user data")
    wheel = tmp_path / "test.whl"
    wheel.touch()
    harness = tmp_path / "check.ps1"
    harness.write_text(r'''param($Root, $Wheel, $Operation)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$global:releaseTestCalls = @()
function Invoke-TestPython { $global:releaseTestCalls += ,@($args); $global:LASTEXITCODE = 0 }
function Get-Command { param($Name, $ErrorAction) return @{ Source = 'Invoke-TestPython' } }
function New-Item { param($Path, [switch]$Force) $global:releaseTestCalls += ,@('create-key', $Path) }
function New-ItemProperty {
    param($Path, $Name, $Value, $PropertyType, [switch]$Force)
    $global:releaseTestCalls += ,@('autostart', $Path, $Name, $Value)
}
function Remove-ItemProperty {
    param($Path, $Name, $ErrorAction)
    $global:releaseTestCalls += ,@('remove-autostart', $Path, $Name)
}
if ($Operation -eq 'uninstall') {
    & "$Root/scripts/uninstall_windows.ps1" | Out-Null
} else {
    & "$Root/scripts/install_windows.ps1" -Wheel $Wheel -EnableAutoStart:($Operation -eq 'autostart') | Out-Null
}
ConvertTo-Json -InputObject @($global:releaseTestCalls) -Depth 5 -Compress
''', encoding="utf-8")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(harness),
                             str(ROOT), str(wheel), operation], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8", check=True)
    calls = json.loads(result.stdout)
    assert sentinel.read_bytes() == b"user data"
    if operation == "uninstall":
        assert calls == [["remove-autostart", r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Run", "Zhaoxi"],
                         ["-m", "pip", "uninstall", "-y", "zhaoxi-lifehud-tool", "zhaoxi"]]
    else:
        assert calls[0] == ["-m", "pip", "install", "--user", "--upgrade", str(wheel)]
        if operation == "install":
            assert len(calls) == 1
        else:
            assert calls[1] == ["create-key", r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"]
            assert calls[2] == ["autostart", calls[1][1], "Zhaoxi", '"Invoke-TestPython" -m zhaoxi --desktop']
