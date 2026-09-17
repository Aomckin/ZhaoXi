$ErrorActionPreference = "Stop"
$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$zhaoxiRoot = Resolve-Path (Join-Path $toolRoot "..\..")
$zhaoxiPython = Join-Path $zhaoxiRoot ".venv\Scripts\python.exe"

$env:ZHAOXI_TOOL_MARKITDOWN_ENABLED = "true"

Set-Location $zhaoxiRoot
if (Test-Path -LiteralPath $zhaoxiPython) {
    & $zhaoxiPython main.py
} else {
    python main.py
}
