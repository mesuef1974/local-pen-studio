param([int]$Port=8770,[switch]$Check)
$ErrorActionPreference='Stop'
$studioRoot=$PSScriptRoot
$cairoFolders=@('C:\Program Files\GTK3-Runtime Win64\bin')
$cairoFolders+=@(Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'bin\postgisgui' })
$cairoFolder=$cairoFolders | Where-Object { Test-Path (Join-Path $_ 'libcairo-2.dll') } | Select-Object -First 1
if(-not $cairoFolder){throw 'لم أجد libcairo-2.dll؛ ثبّت GTK3 runtime أو PostgreSQL ثم أعد المحاولة.'}
$env:PATH="$cairoFolder;$env:PATH"
Write-Output "مسار Cairo: $cairoFolder"
$cairoTest=& python -c "import cairosvg;print(cairosvg.__version__)" 2>&1
if($LASTEXITCODE -ne 0){throw "تعذر تحميل Cairo من هذا المسار: $cairoTest"}
Write-Output "CairoSVG جاهز: $cairoTest"
if($Check){exit 0}
& (Join-Path $studioRoot 'start-server.ps1') -Port $Port
Write-Output 'إن كان الخادم يعمل قبل هذا الأمر فهو يحتفظ بمساره القديم؛ أوقفه وأعد التشغيل ليستعمل Cairo.'
