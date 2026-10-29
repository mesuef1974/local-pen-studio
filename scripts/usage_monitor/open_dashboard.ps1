$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$port = 8769
$url = "http://127.0.0.1:$port/dashboard.html"
$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
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
