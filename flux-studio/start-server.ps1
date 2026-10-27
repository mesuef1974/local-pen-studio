param([int]$Port=8770)
$ErrorActionPreference='Stop'
$studioRoot=$PSScriptRoot
$studioUrl="http://127.0.0.1:$Port"
try {
    $studioStatus=Invoke-RestMethod "$studioUrl/api/status" -TimeoutSec 2
    if($studioStatus.service -ne 'flux-studio'){throw 'المنفذ مستخدم بواسطة تطبيق آخر.'}
    Write-Output "التطبيق يعمل: $studioUrl/prepare"
    exit 0
} catch {
    if(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue){throw 'المنفذ مستخدم؛ لم يبدأ خادم إضافي.'}
}
$studioPython=(Get-Command python -CommandType Application | Select-Object -First 1).Source
$studioProcess=Start-Process -FilePath $studioPython -ArgumentList @('server.py','--port',"$Port") -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput "$studioRoot/server-stdout.log" -RedirectStandardError "$studioRoot/server-stderr.log" -PassThru
for($studioAttempt=0;$studioAttempt -lt 40;$studioAttempt++){
    Start-Sleep -Milliseconds 200
    if($studioProcess.HasExited){throw 'توقف الخادم؛ راجع server-stderr.log.'}
    try {
        $studioStatus=Invoke-RestMethod "$studioUrl/api/status" -TimeoutSec 1
        if($studioStatus.service -eq 'flux-studio'){Write-Output "التطبيق جاهز: $studioUrl/prepare";exit 0}
    } catch {}
}
throw 'لم تؤكد جاهزية الخادم خلال المهلة؛ راجع سجل التشغيل.'
