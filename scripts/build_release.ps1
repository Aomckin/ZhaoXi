param(
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$outputPath = Join-Path $repoRoot $OutputDirectory
$pythonCommand = Get-Command python -ErrorAction Stop

Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
    Get-ChildItem -LiteralPath $outputPath -Filter 'zhaoxi*.whl' -File | Remove-Item -Force
    & $pythonCommand.Source -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    & $pythonCommand.Source -m compileall -q src tools tests
    if ($LASTEXITCODE -ne 0) { throw "Compile check failed." }
    Remove-Item -LiteralPath (Join-Path $repoRoot 'tools\lifehud_tool\__pycache__') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $repoRoot 'tools\lifehud_tool\build') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $repoRoot 'tools\lifehud_tool\zhaoxi_lifehud_tool.egg-info') -Recurse -Force -ErrorAction SilentlyContinue
    & $pythonCommand.Source -m pip wheel . --no-deps --no-build-isolation --wheel-dir $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Wheel build failed." }
    & $pythonCommand.Source -m pip wheel .\tools\lifehud_tool --no-deps --no-build-isolation --wheel-dir $outputPath
    if ($LASTEXITCODE -ne 0) { throw "LifeHUD-Tool wheel build failed." }
    & $pythonCommand.Source scripts\verify_release.py --root $repoRoot --dist $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Release verification failed." }

    $smokeRoot = Join-Path ([IO.Path]::GetTempPath()) ("zhaoxi-release-smoke-" + [Guid]::NewGuid().ToString("N"))
    $smokeSite = Join-Path $smokeRoot "site"
    New-Item -ItemType Directory -Path $smokeSite -Force | Out-Null
    try {
        $coreWheel = (Get-ChildItem -LiteralPath $outputPath -Filter 'zhaoxi-1.0.0-*.whl' -File -ErrorAction Stop).FullName
        $toolWheel = (Get-ChildItem -LiteralPath $outputPath -Filter 'zhaoxi_lifehud_tool-1.0.0-*.whl' -File -ErrorAction Stop).FullName
        & $pythonCommand.Source -m pip install --no-deps --target $smokeSite $coreWheel $toolWheel
        if ($LASTEXITCODE -ne 0) { throw "Clean-target wheel installation failed." }
        $previousPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = $smokeSite
        Push-Location $smokeRoot
        try {
            & $pythonCommand.Source -c "import zhaoxi; from tools.lifehud_tool import create_package; assert zhaoxi.__version__ == '1.0.0'; assert create_package().package_version == '1.0.0'"
            if ($LASTEXITCODE -ne 0) { throw "Installed wheel import smoke failed." }
        }
        finally {
            Pop-Location
            $env:PYTHONPATH = $previousPythonPath
        }
    }
    finally {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
