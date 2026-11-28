# (Re)starts the job worker in the background, so it never runs old code. A job cut short is retried.
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.venv-server\Scripts\python.exe'
if(-not (Test-Path $python)){throw 'The account server environment is missing: see README.md.'}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object {$_.ExecutablePath -eq $python -and $_.CommandLine -match 'manage\.py\W+run_jobs'} |
    ForEach-Object {& taskkill.exe /PID $_.ProcessId /T /F | Out-Null}
$logs=Join-Path $PSScriptRoot 'var'
New-Item -ItemType Directory -Force $logs | Out-Null
Start-Process -FilePath $python -ArgumentList 'manage.py','run_jobs' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$logs\worker-stdout.log" -RedirectStandardError "$logs\worker-stderr.log"
Write-Output 'Job worker started.'
