# Read-only: why can a local process not reach the NVIDIA card right now?
$ErrorActionPreference = 'Continue'
"--- session"
"SessionName=$env:SESSIONNAME  SessionId=$((Get-Process -Id $PID).SessionId)"
(whoami /groups /fo csv | ConvertFrom-Csv | Where-Object { $_.'Group Name' -like 'Mandatory Label*' }).'Group Name'
"--- display devices"
Get-PnpDevice -Class Display | Format-Table Status, Problem, FriendlyName -AutoSize | Out-String
"--- nvidia services"
Get-Service -Name 'NVDisplay.ContainerLocalSystem', 'NvContainerLocalSystem' -ErrorAction SilentlyContinue | Format-Table Status, Name -AutoSize | Out-String
"--- nvidia-smi"
nvidia-smi --query-gpu=name,memory.used,pstate --format=csv,noheader 2>&1
"--- power"
"OnAC=$((Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus -ErrorAction SilentlyContinue | Select-Object -First 1).PowerOnline)"
powercfg /getactivescheme
"--- recent system events (display, power, sleep)"
Get-WinEvent -FilterHashtable @{ LogName = 'System'; StartTime = (Get-Date).AddHours(-14) } -ErrorAction SilentlyContinue |
    Where-Object { $_.ProviderName -match 'nvlddmkm|Display|Kernel-Power|Power-Troubleshooter|Kernel-PnP|TerminalServices|Winlogon' } |
    Select-Object -First 25 TimeCreated, Id, ProviderName, @{ n = 'Message'; e = { ($_.Message -split "`n")[0].Substring(0, [Math]::Min(110, ($_.Message -split "`n")[0].Length)) } } |
    Format-Table -AutoSize -Wrap | Out-String -Width 220
