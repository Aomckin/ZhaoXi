# Regenerate the double-click launcher after moving the project or rebuilding .venv.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$main = Join-Path $projectRoot 'main.py'
if (!(Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw 'Project .venv\Scripts\pythonw.exe is missing. Install the project virtual environment first.'
}
if (!(Test-Path -LiteralPath $main -PathType Leaf)) {
    throw 'Project main.py is missing.'
}
$launcherPath = Join-Path $projectRoot '启动朝汐.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($launcherPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $main + '" --desktop'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = '打开朝汐；已运行时唤起现有窗口'
$shortcut.IconLocation = $pythonw + ',0'
$shortcut.Save()
Write-Output $launcherPath
