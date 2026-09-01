param()

$ErrorActionPreference = "Stop"
$pythonCommand = Get-Command python -ErrorAction Stop
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Remove-ItemProperty -Path $runKey -Name 'Zhaoxi' -ErrorAction SilentlyContinue
& $pythonCommand.Source -m pip uninstall -y zhaoxi
if ($LASTEXITCODE -ne 0) { throw "Zhaoxi uninstall failed." }

Write-Output "Zhaoxi uninstalled. User databases, backups, configuration, and logs under .zhaoxi were preserved."
