# Creates the "masar" PostgreSQL role and database, then writes masar-server\.env.
# Run it yourself: every password is typed at a hidden prompt and never appears on a command line.
# ASCII only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.
param([string]$PgBin = 'C:\Program Files\PostgreSQL\17\bin', [int]$Port = 5432)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $here '.env'
# Leftover test variables in this window would override .env.
Remove-Item Env:MASAR_* -ErrorAction SilentlyContinue
$python = Join-Path $here '.venv-server\Scripts\python.exe'

if (Test-Path $envFile) { throw ".env already exists at $envFile. Delete it yourself to start over." }
if (-not (Test-Path $python)) { throw 'Create .venv-server first (see README.md).' }
$service = Get-Service postgresql-x64-17 -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne 'Running') {
    throw 'PostgreSQL is stopped. In an administrator PowerShell run: Start-Service postgresql-x64-17'
}

$sql = @'
\set ON_ERROR_STOP on
SELECT 'CREATE ROLE masar LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'masar')\gexec
\echo Choose a NEW password for the database role "masar":
\password masar
SELECT 'CREATE DATABASE masar OWNER masar ENCODING ''UTF8'' TEMPLATE template0'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'masar')\gexec
REVOKE CONNECT ON DATABASE masar FROM PUBLIC;
'@
$script = New-TemporaryFile
try {
    Set-Content -Path $script -Value $sql -Encoding Ascii
    Write-Host 'First prompt: the password of the PostgreSQL superuser "postgres".'
    & (Join-Path $PgBin 'psql.exe') -U postgres -h 127.0.0.1 -p $Port -d postgres -f $script.FullName
    if ($LASTEXITCODE -ne 0) { throw 'psql failed; nothing was written.' }
} finally {
    Remove-Item $script -Force
}

$secure = Read-Host 'Type the "masar" password again, to store it in .env' -AsSecureString
$password = [System.Net.NetworkCredential]::new('', $secure).Password
if (-not $password -or $password -ne $password.Trim()) { throw 'Empty password or surrounding spaces; nothing was written.' }
$secret = & $python -c 'import secrets; print(secrets.token_urlsafe(50))'
if ($LASTEXITCODE -ne 0 -or -not $secret) { throw 'Could not generate the secret key; nothing was written.' }
$lines = "MASAR_SECRET_KEY=$secret", "MASAR_DB_PASSWORD=$password", "MASAR_DB_PORT=$Port"
# Restrict the file (this user, SYSTEM, Administrators) before any secret goes into it.
New-Item -ItemType File -Path $envFile | Out-Null
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $envFile /inheritance:r /grant:r "${me}:(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) { Remove-Item $envFile; throw 'Could not restrict .env permissions; nothing was written.' }
[System.IO.File]::WriteAllLines($envFile, $lines)

& $python (Join-Path $here 'manage.py') migrate
# .env was created by this run, so removing it on failure loses nothing and allows a rerun.
if ($LASTEXITCODE -ne 0) { Remove-Item $envFile; throw 'Migration failed (wrong password?). .env was removed; run again.' }
Write-Host 'Done. Next: create the supervisor account (see README.md).'
