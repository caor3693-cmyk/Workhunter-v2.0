param(
    [ValidateRange(1, 65535)][int]$Port = 8766,
    [string]$Database = '',
    [string]$RuntimeDirectory = '',
    [string]$PythonPath = '',
    [ValidateRange(1, 60)][int]$ReadinessTimeoutSeconds = 20
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw "端口 $Port 已占用；不会终止已有进程。" }
if (@(& git status --porcelain -- backend config/schools.json).Count -gt 0) { throw '后端源码尚未固定提交；请提交后再启动可核验构建。' }
if ($LASTEXITCODE -ne 0) { throw '无法核对后端源码身份。' }
$expectedCommit = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $expectedCommit -notmatch '^[a-f0-9]{40}$') { throw '无法固定后端构建身份。' }
if (-not $Database) { $Database = Join-Path $projectDirectory '.runtime/dev/workhunter-v2.sqlite3' }
if (-not (Test-Path -LiteralPath $Database -PathType Leaf)) { throw '独立新库尚未初始化，请先执行 backend.cli init。' }
if (-not $RuntimeDirectory) { $RuntimeDirectory = Join-Path $projectDirectory '.runtime' }
$RuntimeDirectory = [IO.Path]::GetFullPath($RuntimeDirectory)
if (-not $RuntimeDirectory.StartsWith($projectDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '运行材料必须留在本项目目录内。' }
if (-not $PythonPath) { $PythonPath = Join-Path $projectDirectory '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw '项目 Python 环境尚未就绪。' }
$null = New-Item -ItemType Directory -Path $RuntimeDirectory -Force
$tokenFile = Join-Path $RuntimeDirectory 'service-token'
if (-not (Test-Path -LiteralPath $tokenFile)) {
    & $PythonPath -c "import secrets,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_urlsafe(48),encoding='utf-8')" $tokenFile
    if ($LASTEXITCODE -ne 0) { throw '无法建立本地开发凭据。' }
}
$token = [IO.File]::ReadAllText($tokenFile).Trim()
if (-not $token -or $token.Contains("`r") -or $token.Contains("`n")) { throw '本地开发凭据不可用。' }
$originalEnvironment = @{}
foreach ($name in @('WH_API_SERVICE_TOKEN', 'WH_DB_PATH', 'WH_BACKEND_COMMIT')) { $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$process = $null
$ready = $false
$listenerPid = $null
$deadline = [Diagnostics.Stopwatch]::StartNew()

function Get-OwnedListenerPid {
    $owners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' } | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -ne 1) { return $null }
    $owner = [int]$owners[0]
    $ancestor = $owner
    for ($step = 0; $step -lt 16; $step++) {
        if ($ancestor -eq $process.Id) { return $owner }
        $entry = Get-CimInstance Win32_Process -Filter "ProcessId = $ancestor" -OperationTimeoutSec 1 -ErrorAction SilentlyContinue
        if (-not $entry -or [int]$entry.ParentProcessId -le 0 -or [int]$entry.ParentProcessId -eq $ancestor) { return $null }
        $ancestor = [int]$entry.ParentProcessId
    }
    return $null
}

function Read-Identity([string]$Route) {
    $remaining = ($ReadinessTimeoutSeconds * 1000) - $deadline.ElapsedMilliseconds
    if ($remaining -le 0) { throw '就绪检查超时。' }
    $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$Port$Route")
    $request.Proxy = $null
    $request.Method = 'GET'
    $request.AllowAutoRedirect = $false
    $request.Timeout = [int][Math]::Min(1500, $remaining)
    $request.ReadWriteTimeout = $request.Timeout
    $request.Headers['Authorization'] = 'Bearer ' + $token
    $response = $null
    $reader = $null
    try {
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200 -or $response.ContentType -notmatch '^application/json\b') { throw '身份响应不可读。' }
        $stream = $response.GetResponseStream()
        $reader = New-Object IO.StreamReader($stream)
        $body = New-Object Text.StringBuilder
        $buffer = New-Object char[] 4096
        while ($true) {
            $remaining = ($ReadinessTimeoutSeconds * 1000) - $deadline.ElapsedMilliseconds
            if ($remaining -le 0) { throw '就绪检查超时。' }
            if ($stream.CanTimeout) { $stream.ReadTimeout = [int][Math]::Min(1500, $remaining) }
            $count = $reader.Read($buffer, 0, $buffer.Length)
            if ($count -eq 0) { break }
            if ($body.Length + $count -gt 65536) { throw '身份响应超过检查上限。' }
            $null = $body.Append($buffer, 0, $count)
        }
        return ($body.ToString() | ConvertFrom-Json)
    } finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Dispose() }
    }
}

try {
    $env:WH_API_SERVICE_TOKEN = $token
    $env:WH_DB_PATH = [IO.Path]::GetFullPath($Database)
    $env:WH_BACKEND_COMMIT = $expectedCommit
    $process = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'backend.cli', 'serve', '--port', "$Port") -WorkingDirectory $projectDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeDirectory 'api.stdout.log') -RedirectStandardError (Join-Path $RuntimeDirectory 'api.stderr.log') -PassThru
    while ($deadline.Elapsed.TotalSeconds -lt $ReadinessTimeoutSeconds) {
        $process.Refresh()
        if ($process.HasExited) { throw '开发 API 启动进程已退出；请检查本项目运行日志。' }
        try {
            $health = Read-Identity '/health'
            $version = Read-Identity '/version'
            $same = $true
            foreach ($field in @('project', 'version', 'stage', 'backend_commit', 'dataset_id', 'data_mode')) {
                if (-not ($health.$field -is [string]) -or -not $health.$field -or $health.$field -ne $version.$field) { $same = $false }
            }
            if ($same -and $health.status -eq 'ok' -and $health.database -eq 'readable' -and $health.project -eq 'Workhunter-v2.0' -and $health.backend_commit -eq $expectedCommit) {
                $listenerPid = Get-OwnedListenerPid
                $process.Refresh()
                if ($listenerPid -and -not $process.HasExited -and $deadline.Elapsed.TotalSeconds -lt $ReadinessTimeoutSeconds) {
                    $ready = $true
                    break
                }
            }
        } catch { }
        $remaining = ($ReadinessTimeoutSeconds * 1000) - $deadline.ElapsedMilliseconds
        if ($remaining -gt 0) { Start-Sleep -Milliseconds ([int][Math]::Min(200, $remaining)) }
    }
    if (-not $ready) { throw '开发 API 未在限定时间内取得一致构建与数据身份。' }
    $listenerPid | Set-Content -LiteralPath (Join-Path $RuntimeDirectory 'api.pid')
    [ordered]@{pid = $listenerPid; launcher_pid = $process.Id; listener_pid = $listenerPid; port = $Port; project = $version.project; version = $version.version; stage = $version.stage; backend_commit = $version.backend_commit; dataset_id = $version.dataset_id; data_mode = $version.data_mode; observed_at = [DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeDirectory 'api.ready.json') -Encoding UTF8
    Write-Output "开发 API 已就绪（监听 PID $listenerPid，启动器 PID $($process.Id)），构建 $expectedCommit，数据集 $($version.dataset_id)，模式 $($version.data_mode)。"
} catch {
    if ($process) {
        $process.Refresh()
        if (-not $process.HasExited) {
            # The Windows virtualenv launcher can own a Python child; stop only this new tree.
            & taskkill.exe /PID "$($process.Id)" /T /F *> $null
        }
    }
    throw '开发 API 启动或就绪检查失败；未清理既有进程，请检查本项目运行日志。'
} finally {
    foreach ($name in $originalEnvironment.Keys) {
        if ($null -eq $originalEnvironment[$name]) { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process') }
    }
    $token = $null
}
