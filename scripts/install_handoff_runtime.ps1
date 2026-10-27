param(
    [Parameter(Mandatory = $false)]
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$coordinator = Join-Path $rootPath 'scripts\handoff_coordinator.py'
$codex = (Get-Command codex.exe -ErrorAction Stop).Source
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $coordinator)) {
    throw 'Coordinator script is missing.'
}

$taskName = 'Masar HANDOFF0001 Coordinator'
$arguments = '-X utf8 "{0}" once --root "{1}" --codex "{2}"' -f $coordinator, $rootPath, $codex
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $rootPath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Starts the create-only HANDOFF0001 coordinator; never archives a session.'
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

[pscustomobject]@{
    TaskName = $taskName
    Root = $rootPath
    Python = $python
    Codex = $codex
    SessionCreation = $true
    SessionArchive = $false
}
