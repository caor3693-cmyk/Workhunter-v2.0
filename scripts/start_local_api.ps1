param([int]$Port = 8766)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
if ((& git status --porcelain -- backend config/schools.json).Count -gt 0) { throw '后端源码尚未固定提交；请提交后再启动可核验构建。' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw "端口 $Port 已占用；不会终止已有进程。" }
$database = Join-Path $projectDirectory '.runtime/dev/workhunter-v2.sqlite3'
if (-not (Test-Path -LiteralPath $database)) { throw '独立新库尚未初始化，请先执行 backend.cli init。' }
$tokenFile = Join-Path $projectDirectory '.runtime/service-token'
if (-not (Test-Path -LiteralPath $tokenFile)) {
    & .venv/Scripts/python.exe -c "import secrets,pathlib; pathlib.Path('.runtime/service-token').write_text(secrets.token_urlsafe(48),encoding='utf-8')"
    if ($LASTEXITCODE -ne 0) { throw '无法建立本地开发凭据。' }
}
$env:WH_API_SERVICE_TOKEN = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
$env:WH_DB_PATH = $database
$env:WH_BACKEND_COMMIT = (& git rev-parse HEAD).Trim()
try {
    $process = Start-Process -FilePath (Join-Path $projectDirectory '.venv/Scripts/python.exe') -ArgumentList @('-m','backend.cli','serve','--port',"$Port") -WorkingDirectory $projectDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectDirectory '.runtime/api.stdout.log') -RedirectStandardError (Join-Path $projectDirectory '.runtime/api.stderr.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $projectDirectory '.runtime/api.pid')
    Write-Output "开发 API 已启动（PID $($process.Id)），须读取 /health 验证就绪。凭据未显示。"
} finally {
    Remove-Item Env:WH_API_SERVICE_TOKEN,Env:WH_DB_PATH,Env:WH_BACKEND_COMMIT -ErrorAction SilentlyContinue
}
