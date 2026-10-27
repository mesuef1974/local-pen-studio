param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = 'Codex Usage Logger'
)

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$logger = Join-Path $rootPath 'scripts\codex_usage_logger.py'
$python = (Get-Command python.exe -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $logger -PathType Leaf)) {
    throw "Usage logger was not found: $logger"
}

$action = New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "{0}"' -f $logger)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew -Hidden

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings `
    -Description 'Records local per-session Codex token and allowance metrics without model calls.' `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
