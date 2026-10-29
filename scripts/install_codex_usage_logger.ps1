param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = 'Codex Usage Logger'
)

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$sourceMonitor = Join-Path $rootPath 'scripts\usage_monitor'
$sourceIdentity = Join-Path $rootPath 'docs\coordination\assets'
$databaseSource = Join-Path $sourceMonitor 'usage_database.py'
$loggerSource = Join-Path $sourceMonitor 'codex_usage_logger.py'
$python = (Get-Command python.exe -ErrorAction Stop).Source
foreach ($required in @($databaseSource, $loggerSource, (Join-Path $sourceMonitor 'dashboard_server.py'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "ملف القياس المطلوب غير موجود: $required" }
}
foreach ($required in @((Join-Path $sourceIdentity 'identity.css'),
        (Join-Path $sourceIdentity 'fonts\cairo-arabic.woff2'),
        (Join-Path $sourceIdentity 'fonts\ibm-plex-sans-arabic.woff2'),
        (Join-Path $sourceIdentity 'fonts\manrope-latin.woff2'),
        (Join-Path $sourceIdentity 'fonts\plus-jakarta-sans-latin.woff2'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "أصل الهوية المشتركة غير موجود: $required" }
}

$schemaMatch = [regex]::Match((Get-Content -LiteralPath $databaseSource -Raw), '(?m)^SCHEMA_VERSION\s*=\s*(\d+)')
if (-not $schemaMatch.Success) { throw 'تعذر تحديد إصدار مخطط قاعدة البيانات من نسخة القياس.' }
$sourceSchema = [int]$schemaMatch.Groups[1].Value
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$codexHome = [IO.Path]::GetFullPath($codexHome)
$databasePath = Join-Path $codexHome 'usage-logs\usage.sqlite3'
$databaseSchema = 0
if (Test-Path -LiteralPath $databasePath -PathType Leaf) {
    $databaseSchema = [int](& $python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("PRAGMA user_version").fetchone()[0]); c.close()' $databasePath)
    if ($LASTEXITCODE -ne 0) { throw 'تعذر قراءة إصدار قاعدة القياس؛ لم تُحدّث المهمة المجدولة.' }
}
if ($sourceSchema -lt $databaseSchema) {
    throw "رفض التثبيت: كود القياس يدعم مخطط $sourceSchema، وقاعدة البيانات إصدارها $databaseSchema. استخدم نسخة أحدث من جذر المشروع؛ لم تُغيّر المهمة الحالية."
}

# Use a content-addressed runtime outside Git/worktrees so the task cannot point
# at a temporary checkout that later changes branch or disappears.
$runtimeRoot = Join-Path $codexHome 'usage-monitor-runtime'
$releaseRoot = Join-Path $runtimeRoot 'releases'
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
function Get-ContentFingerprint([string]$Path, [string]$IdentityPath) {
    $basePath = (Resolve-Path -LiteralPath $Path).Path
    $identityBasePath = (Resolve-Path -LiteralPath $IdentityPath).Path
    $runtimeFiles = Get-ChildItem -LiteralPath $basePath -File -Recurse |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__([\\/]|$)' -and $_.Extension -ne '.pyc' -and $_.Name -ne 'runtime.json' } |
        Where-Object { $_.FullName -notmatch '[\\/]shared_identity([\\/]|$)' } |
        ForEach-Object { [pscustomobject]@{ RelativePath = 'runtime/' + $_.FullName.Substring($basePath.Length).Replace('\','/'); File = $_ } }
    $identityFiles = Get-ChildItem -LiteralPath $identityBasePath -File -Recurse |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__([\\/]|$)' -and $_.Extension -ne '.pyc' } |
        ForEach-Object { [pscustomobject]@{ RelativePath = 'shared_identity/' + $_.FullName.Substring($identityBasePath.Length).Replace('\','/'); File = $_ } }
    $files = @($runtimeFiles) + @($identityFiles) | Sort-Object RelativePath
    $fingerprintInput = ($files | ForEach-Object {
        '{0}:{1}' -f $_.RelativePath,
            (Get-FileHash -LiteralPath $_.File.FullName -Algorithm SHA256).Hash
    }) -join "`n"
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToHexString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($fingerprintInput))).ToLowerInvariant() }
    finally { $sha.Dispose() }
}
$fingerprint = Get-ContentFingerprint $sourceMonitor $sourceIdentity
$releaseName = 'schema-{0}-{1}' -f $sourceSchema, $fingerprint.Substring(0, 16)
$releasePath = Join-Path $releaseRoot $releaseName
$activePath = Join-Path $runtimeRoot 'active.json'
$manifest = [ordered]@{
    runtime_path = $releasePath
    source_root = $rootPath
    source_commit = ((& git -C $rootPath rev-parse HEAD 2>$null) -join '').Trim()
    code_sha256 = $fingerprint
    collector_version = '4'
    schema_version = $sourceSchema
    database_path = $databasePath
    installed_at = [DateTime]::UtcNow.ToString('o')
}
if (-not (Test-Path -LiteralPath $releasePath -PathType Container)) {
    $stagePath = Join-Path $releaseRoot ('.staging-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stagePath | Out-Null
    try {
        foreach ($item in Get-ChildItem -LiteralPath $sourceMonitor -Force) {
            if ($item.Name -eq '__pycache__') { continue }
            Copy-Item -LiteralPath $item.FullName -Destination $stagePath -Recurse -Force
        }
        $identityStagePath = Join-Path $stagePath 'shared_identity'
        New-Item -ItemType Directory -Path $identityStagePath | Out-Null
        foreach ($item in Get-ChildItem -LiteralPath $sourceIdentity -Force) {
            Copy-Item -LiteralPath $item.FullName -Destination $identityStagePath -Recurse -Force
        }
        $stagedSchemaMatch = [regex]::Match((Get-Content -LiteralPath (Join-Path $stagePath 'usage_database.py') -Raw), '(?m)^SCHEMA_VERSION\s*=\s*(\d+)')
        if (-not $stagedSchemaMatch.Success -or [int]$stagedSchemaMatch.Groups[1].Value -ne $sourceSchema) {
            throw 'نسخة القياس المنسوخة لا تطابق إصدار المخطط الذي جرى التحقق منه.'
        }
        if ((Get-ContentFingerprint $stagePath (Join-Path $stagePath 'shared_identity')) -ne $fingerprint) {
            throw 'بصمة ملفات نسخة القياس المرحلية لا تطابق المصدر؛ لم يُفعّل الإصدار.'
        }
        $stageFull = [IO.Path]::GetFullPath($stagePath)
        $releaseFull = [IO.Path]::GetFullPath($releaseRoot)
        if (-not $stageFull.StartsWith($releaseFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'رفض نقل مجلد وسيط خارج مجلد إصدارات القياس.'
        }
        Move-Item -LiteralPath $stagePath -Destination $releasePath
    } catch {
        $stageFull = [IO.Path]::GetFullPath($stagePath)
        $runtimeFull = [IO.Path]::GetFullPath($runtimeRoot)
        if ((Test-Path -LiteralPath $stagePath) -and $stageFull.StartsWith($runtimeFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $stagePath -Recurse -Force
        }
        throw
    }
} elseif ((Get-ContentFingerprint $releasePath (Join-Path $releasePath 'shared_identity')) -ne $fingerprint) {
    throw 'محتويات الإصدار الموجود لا تطابق بصمته؛ أوقف التثبيت لحماية النسخة النشطة.'
}

$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $releasePath 'runtime.json') -Encoding utf8
$activeTemp = Join-Path $runtimeRoot ('.active-' + [guid]::NewGuid().ToString('N') + '.json')
$activeBackup = Join-Path $runtimeRoot ('.active-backup-' + [guid]::NewGuid().ToString('N') + '.json')
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $activeTemp -Encoding utf8

$runtimeLogger = Join-Path $releasePath 'codex_usage_logger.py'
$arguments = '-X utf8 "{0}" --sessions-root "{1}" --index "{2}" --database "{3}" --legacy-sessions "{4}" --legacy-state "{5}"' -f `
    $runtimeLogger, (Join-Path $codexHome 'sessions'), (Join-Path $codexHome 'session_index.jsonl'),
    $databasePath, (Join-Path $codexHome 'usage-logs\sessions'), (Join-Path $codexHome 'usage-logs\state.json')
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $releasePath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew -Hidden
$previousTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$hadActiveManifest = Test-Path -LiteralPath $activePath -PathType Leaf
$manifestActivated = $false
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Collects local Codex token metrics from a versioned runtime compatible with the local SQLite schema.' `
        -Force | Out-Null
    if (Test-Path -LiteralPath $activePath -PathType Leaf) {
        [IO.File]::Replace($activeTemp, $activePath, $activeBackup)
    } else {
        [IO.File]::Move($activeTemp, $activePath)
    }
    $manifestActivated = $true
    Start-ScheduledTask -TaskName $TaskName
} catch {
    if ($manifestActivated -and (Test-Path -LiteralPath $activeBackup -PathType Leaf)) {
        try { [IO.File]::Replace($activeBackup, $activePath, $null) }
        catch { Write-Warning "تعذر استرجاع manifest السابق تلقائيًا: $($_.Exception.Message)" }
    } elseif ($manifestActivated -and -not $hadActiveManifest) {
        Remove-Item -LiteralPath $activePath -Force -ErrorAction SilentlyContinue
    }
    if ($previousTask) {
        try {
            Set-ScheduledTask -TaskName $TaskName -Action $previousTask.Actions `
                -Trigger $previousTask.Triggers -Settings $previousTask.Settings | Out-Null
        } catch { Write-Warning "تعذر استرجاع المهمة المجدولة السابقة تلقائيًا: $($_.Exception.Message)" }
    } else {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    throw
} finally {
    Remove-Item -LiteralPath $activeTemp -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $activeBackup -Force -ErrorAction SilentlyContinue
}
$databaseSchemaAfterStart = [int](& $python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("PRAGMA user_version").fetchone()[0]); c.close()' $databasePath)
[pscustomobject]@{
    TaskName = $TaskName
    Runtime = $releasePath
    CollectorVersion = $manifest.collector_version
    SourceSchema = $sourceSchema
    DatabaseSchemaBeforeInstall = $databaseSchema
    DatabaseSchemaAtReturn = $databaseSchemaAfterStart
    Database = $databasePath
} | Format-List
