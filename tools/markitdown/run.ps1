param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,

    [Parameter(Position = 1)]
    [string]$OutputFile
)

$markitdown = Join-Path $PSScriptRoot ".venv\Scripts\markitdown.exe"

if (-not (Test-Path -LiteralPath $markitdown)) {
    throw "MarkItDown is not installed at $markitdown"
}

if ($OutputFile) {
    & $markitdown $InputFile -o $OutputFile
} else {
    & $markitdown $InputFile
}

exit $LASTEXITCODE
