param(
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$outputPath = Join-Path $repoRoot $OutputDirectory
$pythonCommand = Get-Command python -ErrorAction Stop

Push-Location $repoRoot
try {
    & $pythonCommand.Source -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    & $pythonCommand.Source -m compileall -q src tests
    if ($LASTEXITCODE -ne 0) { throw "Compile check failed." }
    & $pythonCommand.Source -m pip wheel . --no-deps --no-build-isolation --wheel-dir $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Wheel build failed." }
    Get-ChildItem -LiteralPath $outputPath -Filter '*.whl' |
        Get-FileHash -Algorithm SHA256 |
        Select-Object Hash, Path |
        ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $outputPath 'SHA256SUMS.json') -Encoding utf8
}
finally {
    Pop-Location
}
