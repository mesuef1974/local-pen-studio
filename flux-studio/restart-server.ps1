param([int]$Port=8770)
$ErrorActionPreference='Stop'
$studioRoot=$PSScriptRoot
# Some Windows builds report the listening socket with an empty State, so match it by owner and remote port.
function Get-StudioListener{Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object {$_.OwningProcess -ne 0 -and $_.RemotePort -eq 0} | Select-Object -First 1}
$listener=Get-StudioListener
if($listener){
    $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    # Stop only this studio's own server; never another program that happens to hold the port.
    if($owner.CommandLine -notmatch 'server\.py' -or $owner.CommandLine -notmatch "--port\W+$Port"){throw 'المنفذ يستعمله برنامج آخر؛ لم أوقف شيئًا.'}
    $studioStatus=Invoke-RestMethod "http://127.0.0.1:$Port/api/status" -TimeoutSec 2
    if($studioStatus.service -ne 'flux-studio'){throw 'المنفذ يستعمله تطبيق آخر؛ لم أوقف شيئًا.'}
    Stop-Process -Id $owner.ProcessId
    for($attempt=0;$attempt -lt 25 -and (Get-StudioListener);$attempt++){Start-Sleep -Milliseconds 200}
    Write-Output "أُوقف الخادم السابق ($($owner.ProcessId))."
}
& (Join-Path $studioRoot 'start-server.ps1') -Port $Port
