"""Current-user Windows logon task; no passwords or elevation required."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

# Input is JSON on stdin, never interpolated into executable PowerShell code.
_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    $config = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $name = 'Zhaoxi-Desktop-' + $sid
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $existing = $null
    foreach ($candidate in $folder.GetTasks(1)) {
        if ($candidate.Name -eq $name) { $existing = $candidate; break }
    }
    if ($config.action -eq 'install') {
        $task = $service.NewTask(0)
        $task.RegistrationInfo.Description = 'Zhaoxi Desktop current-user background presence'
        $task.Principal.UserId = $sid
        $task.Principal.LogonType = 3
        $task.Principal.RunLevel = 0
        $trigger = $task.Triggers.Create(9)
        $trigger.UserId = $sid
        $trigger.Delay = 'PT8S'
        $task.Settings.Enabled = $true
        $task.Settings.MultipleInstances = 2
        $task.Settings.ExecutionTimeLimit = 'PT0S'
        $task.Settings.DisallowStartIfOnBatteries = $false
        $task.Settings.StopIfGoingOnBatteries = $false
        $task.Settings.StartWhenAvailable = $true
        $task.Settings.RestartCount = 0
        $exec = $task.Actions.Create(0)
        $exec.Path = $config.executable
        $exec.Arguments = $config.arguments
        $exec.WorkingDirectory = $config.directory
        $existing = $folder.RegisterTaskDefinition($name, $task, 6, $sid, $null, 3, $null)
    } elseif ($config.action -eq 'remove') {
        if ($null -ne $existing) { $folder.DeleteTask($name, 0) }
        $existing = $null
    }
    $result = @{task_name=$name; installed=($null -ne $existing)}
    if ($null -ne $existing) {
        $result.enabled = $existing.Enabled
        $result.state = $existing.State
        $result.last_result = $existing.LastTaskResult
        $result.executable = $existing.Definition.Actions.Item(1).Path
        $result.arguments = $existing.Definition.Actions.Item(1).Arguments
        $result.directory = $existing.Definition.Actions.Item(1).WorkingDirectory
    }
    $result | ConvertTo-Json -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
'''


def launch_config() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    executable = Path(sys.executable).absolute().with_name('pythonw.exe')
    if sys.prefix == sys.base_prefix or not executable.is_file():
        raise RuntimeError('请使用项目虚拟环境的 Python 安装自启动；需要同目录 pythonw.exe。')
    if not (root / 'main.py').is_file():
        raise RuntimeError('找不到项目 main.py，请从源码项目的虚拟环境安装。')
    return {
        'executable': str(executable),
        'arguments': subprocess.list2cmdline([str(root / 'main.py'), '--desktop', '--background']),
        'directory': str(root),
    }


def manage_autostart(action: str) -> dict:
    if action not in {'install', 'status', 'remove'}:
        raise ValueError(f'Unknown autostart action: {action}')
    if sys.platform != 'win32':
        raise RuntimeError('登录自启动仅支持 Windows。')
    payload = {'action': action}
    if action == 'install':
        payload.update(launch_config())
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand',
             base64.b64encode(_SCRIPT.encode('utf-16le')).decode('ascii')],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'无法访问 Windows 任务计划程序：{exc}') from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or '任务计划程序操作失败。')
    try:
        return json.loads(result.stdout.lstrip('\ufeff'))
    except ValueError as exc:
        raise RuntimeError('任务计划程序返回了无法识别的结果。') from exc


