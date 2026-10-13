[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$DatabasePath,
    [Parameter(Mandatory=$true)][string]$BackupDirectory,
    [string]$TaskName,
    [string]$FirstRun
)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskPython = (Resolve-Path -LiteralPath $PythonPath).Path
$taskDatabase = (Resolve-Path -LiteralPath $DatabasePath).Path
$taskBackup = [IO.Path]::GetFullPath($BackupDirectory)
$taskPythonWindowless = Join-Path (Split-Path -Parent $taskPython) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $taskPythonWindowless -PathType Leaf)) { throw '需要同一环境的 pythonw.exe，避免任务弹出终端。' }
$taskUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$taskDigest = [Security.Cryptography.SHA256]::Create()
try { $taskHash = ([BitConverter]::ToString($taskDigest.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskDatabase.ToLowerInvariant())))).Replace('-','').Substring(0,12) }
finally { $taskDigest.Dispose() }
if (-not $TaskName) { $TaskName = "WorkhunterV2-M3-$taskUserSid-$taskHash" }
if ($TaskName -notmatch '^WorkhunterV2-M3-[A-Za-z0-9_-]+$') { throw '任务名必须属于当前 WorkhunterV2-M3 独立命名空间。' }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw '同名任务已存在，停止；不会覆盖现有或旧站任务。' }
foreach ($taskArgument in @($taskRoot,$taskPythonWindowless,$taskDatabase,$taskBackup,$TaskName)) {
    if ($taskArgument -match '["\r\n]') { throw '任务参数包含不支持的字符。' }
}
$taskStart = if ($FirstRun) { [DateTimeOffset]::Parse($FirstRun) } else { [DateTimeOffset]::Now.AddMinutes(2) }
if ($taskStart -le [DateTimeOffset]::Now) { throw '首个自然启动必须排在当前时间之后。' }
$taskPolicy = Get-Content -LiteralPath (Join-Path $taskRoot 'config/operations.json') -Raw | ConvertFrom-Json
$taskInterval = [int]$taskPolicy.interval_hours
if ($taskInterval -lt 1 -or $taskInterval -gt 168) { throw '调度间隔超出已登记范围。' }
$taskRegistrationId = "windows-task:$TaskName"
$taskArguments = "-m ops.scheduler tick --db `"$taskDatabase`" --backup-directory `"$taskBackup`" --trigger scheduled --registration-id `"$taskRegistrationId`""
$taskTrigger = New-ScheduledTaskTrigger -Once -At $taskStart.LocalDateTime -RepetitionInterval (New-TimeSpan -Hours $taskInterval)
$taskAction = New-ScheduledTaskAction -Execute $taskPythonWindowless -Argument $taskArguments -WorkingDirectory $taskRoot
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUserSid -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds ([int]$taskPolicy.round_seconds + 180))
$taskReceiptPath = Join-Path (Split-Path -Parent $taskDatabase) ('.host-registration-' + [Guid]::NewGuid().ToString('N') + '.json')
Push-Location -LiteralPath $taskRoot
try {
    # Until the actual task can be read back, business scheduling stays disabled.
    & $taskPython -m ops.scheduler configure --db $taskDatabase --first-run $taskStart.ToString('o')
    if ($LASTEXITCODE -ne 0) { throw '隔离库未准备好，未注册宿主任务。' }
    Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings | Out-Null
    $taskReadback = Get-ScheduledTask -TaskName $TaskName
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
    $taskReadStart = [DateTimeOffset]::Parse($taskReadback.Triggers[0].StartBoundary)
    $taskReadSid = if ($taskReadback.Principal.UserId -match '^S-\d-') { $taskReadback.Principal.UserId }
        else { ([Security.Principal.NTAccount]::new($taskReadback.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value }
    if ($taskReadback.Actions[0].Execute -ne $taskPythonWindowless -or $taskReadback.Actions[0].Arguments -ne $taskArguments -or
        $taskReadback.Actions[0].WorkingDirectory -ne $taskRoot -or $taskReadSid -ne $taskUserSid -or
        [int]$taskReadback.Principal.RunLevel -ne 0 -or [int]$taskReadback.State -eq 1 -or
        $taskReadback.Triggers[0].Repetition.Interval -ne "PT${taskInterval}H" -or
        [Math]::Abs(($taskReadStart - $taskStart).TotalSeconds) -gt 1 -or
        [Math]::Abs((([DateTimeOffset]$taskInfo.NextRunTime) - $taskStart).TotalSeconds) -gt 2) {
        throw '宿主登记回读不符合本次身份、权限、周期或首个计划；业务调度仍未启用。'
    }
    $taskReceipt = @{ id=$taskRegistrationId; platform='windows-task'; readback_verified=$true; enabled=$true;
        interval_hours=$taskInterval; first_run_at=$taskReadStart.ToString('o'); verified_at=[DateTimeOffset]::Now.ToString('o') }
    $taskReceipt | ConvertTo-Json | Set-Content -LiteralPath $taskReceiptPath -Encoding utf8
    & $taskPython -m ops.scheduler configure --db $taskDatabase --first-run $taskReadStart.ToString('o') --host-registration $taskReceiptPath
    if ($LASTEXITCODE -ne 0) { throw '宿主已登记但业务启用失败，需核对同名任务；不会自动覆盖或删除。' }
    [pscustomobject]@{ task_name=$TaskName; registration_id=$taskRegistrationId; first_run_at=$taskReadStart.ToString('o');
        interval_hours=$taskInterval; principal=$taskUserSid; run_level='Limited'; next_run_at=([DateTimeOffset]$taskInfo.NextRunTime).ToString('o');
        bootstrap_note='首个未来启动为真实bootstrap计划，之后按固定周期；未发生六小时运营观察。' } | ConvertTo-Json
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $taskReceiptPath -PathType Leaf) { Remove-Item -LiteralPath $taskReceiptPath }
}
