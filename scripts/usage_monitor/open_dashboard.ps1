$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$port = 8769
$url = "http://127.0.0.1:$port/dashboard.html"
$healthUrl = "http://127.0.0.1:$port/api/health"
$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $health = $null
    try { $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 } catch { }
    if (-not $health -or $health.schema_version -lt 6 -or -not $health.dispatcher_enabled) {
        $processIds = @($existing | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($processId in $processIds) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
            if (-not $process -or $process.CommandLine -notmatch '[\\/]scripts[\\/]usage_monitor[\\/]dashboard_server\.py') {
                throw "المنفذ $port مستخدم بخدمة غير معروفة؛ لن أوقفها تلقائيًا."
            }
            Stop-Process -Id $processId -Force
        }
        $deadline = (Get-Date).AddSeconds(10)
        do {
            Start-Sleep -Milliseconds 250
            $existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        } while ($existing -and (Get-Date) -lt $deadline)
        if ($existing) { throw "تعذر إيقاف النسخة القديمة من خادم لوحة الاستخدام بأمان." }
    }
}
if (-not $existing) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $server = Join-Path $root 'dashboard_server.py'
    $arguments = '-X utf8 "{0}" --port {1}' -f $server, $port
    Start-Process -FilePath $python -ArgumentList $arguments `
        -WorkingDirectory $root -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    } while (-not $existing -and (Get-Date) -lt $deadline)
}
if (-not $existing) { throw "تعذر بدء خادم لوحة القياس المحلي على المنفذ $port." }
Start-Process $url
