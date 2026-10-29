$ErrorActionPreference = 'Stop'
$port = 8769
$url = "http://127.0.0.1:$port/dashboard.html"
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$codexHome = [IO.Path]::GetFullPath($codexHome)
$runtimeRoot = Join-Path $codexHome 'usage-monitor-runtime'
$releasesRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot 'releases'))
$activeFile = Join-Path $runtimeRoot 'active.json'
if (-not (Test-Path -LiteralPath $activeFile -PathType Leaf)) {
    throw 'لم يُثبّت إصدار قياس ثابت بعد. شغّل scripts/install_codex_usage_logger.ps1 أولًا.'
}
$active = Get-Content -LiteralPath $activeFile -Raw | ConvertFrom-Json
$runtime = [IO.Path]::GetFullPath([string]$active.runtime_path)
if (-not $runtime.StartsWith($releasesRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'مسار تشغيل لوحة القياس خارج مجلد الإصدارات المحلية الموثوقة.'
}
$server = Join-Path $runtime 'dashboard_server.py'
if (-not (Test-Path -LiteralPath $server -PathType Leaf)) { throw "خادم لوحة القياس غير موجود في الإصدار النشط: $runtime" }
$database = if ($active.database_path) { [string]$active.database_path } else { Join-Path $codexHome 'usage-logs\usage.sqlite3' }
$python = (Get-Command python.exe -ErrorAction Stop).Source
$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($existing.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = [string]$process.CommandLine
    $expected = $commandLine.Contains($server, [StringComparison]::OrdinalIgnoreCase)
    if (-not $expected) {
        $knownDashboard = $commandLine -match 'dashboard_server\.py.*--port\s+8769|manage\.py runserver 127\.0\.0\.1:8769'
        if (-not $knownDashboard) { throw "المنفذ 8769 مشغول بعملية أخرى؛ لن أوقفها تلقائيًا. PID=$($existing.OwningProcess)" }
        Stop-Process -Id $existing.OwningProcess -Force
        $deadline = (Get-Date).AddSeconds(10)
        do {
            Start-Sleep -Milliseconds 250
            $existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        } while ($existing -and (Get-Date) -lt $deadline)
        if ($existing) { throw 'توقفت نسخة قديمة من لوحة القياس لكن المنفذ لم يُخلَ.' }
    }
}
if (-not $existing) {
    $arguments = '-X utf8 "{0}" --host 127.0.0.1 --port {1} --database "{2}"' -f $server, $port, $database
    Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $runtime -WindowStyle Hidden | Out-Null
    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        $existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    } while (-not $existing -and (Get-Date) -lt $deadline)
}
if (-not $existing) { throw "تعذر بدء لوحة القياس من الإصدار المحلي $runtime." }
try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/dashboard" -UseBasicParsing -TimeoutSec 10
} catch { throw "خادم القياس استمع إلى المنفذ لكنه لم يقدم API صالحًا: $($_.Exception.Message)" }
Start-Process $url
