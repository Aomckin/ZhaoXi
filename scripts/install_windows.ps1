param(
    [Parameter(Mandatory = $true)]
    [string]$Wheel,
    [switch]$EnableAutoStart
)

$ErrorActionPreference = "Stop"
$wheelPath = (Resolve-Path -LiteralPath $Wheel).Path
if ([IO.Path]::GetExtension($wheelPath) -ne '.whl') { throw "Wheel must be a .whl file." }
$pythonCommand = Get-Command python -ErrorAction Stop

& $pythonCommand.Source -m pip install --user --upgrade $wheelPath
if ($LASTEXITCODE -ne 0) { throw "Zhaoxi installation failed." }

if ($EnableAutoStart) {
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $command = '"' + $pythonCommand.Source + '" -m zhaoxi --desktop'
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty -Path $runKey -Name 'Zhaoxi' -Value $command -PropertyType String -Force | Out-Null
}

Write-Output "Zhaoxi installed. User data remains under the configured .zhaoxi directory."
