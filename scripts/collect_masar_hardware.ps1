# Read-only hardware and local compute inventory for Masar path-processing review.
# Run in PowerShell (Administrator is optional; no changes or installations are made).
$ErrorActionPreference = 'Continue'
$report = New-Object System.Collections.Generic.List[string]
function Add-Section([string]$Title) {
    $report.Add('')
    $report.Add(('=' * 72))
    $report.Add($Title)
    $report.Add(('=' * 72))
}
function Add-Text([object]$Value) {
    if ($null -eq $Value) { $report.Add('غير متاح'); return }
    foreach ($line in @($Value)) { $report.Add([string]$line) }
}

Add-Section 'تقرير عتاد مسار — قراءة فقط'
Add-Text ('وقت الجمع: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'))
Add-Text 'لا يجمع هذا التقرير الرقم التسلسلي أو اسم المستخدم أو محتوى الملفات.'

Add-Section 'نظام التشغيل'
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    Add-Text ("النظام: {0}; الإصدار: {1}; البناء: {2}; البنية: {3}" -f $os.Caption, $os.Version, $os.BuildNumber, $os.OSArchitecture)
} catch { Add-Text ('تعذر قراءة النظام: ' + $_.Exception.Message) }

Add-Section 'المعالج'
try {
    Get-CimInstance Win32_Processor -ErrorAction Stop | ForEach-Object {
        Add-Text ("{0} | أنوية: {1} | خيوط منطقية: {2} | أقصى تردد معلن: {3} MHz" -f $_.Name, $_.NumberOfCores, $_.NumberOfLogicalProcessors, $_.MaxClockSpeed)
    }
} catch { Add-Text ('تعذر قراءة المعالج: ' + $_.Exception.Message) }

Add-Section 'ذاكرة النظام وشرائح RAM'
try {
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    Add-Text ("إجمالي RAM المركبة: {0:N1} GiB" -f ($cs.TotalPhysicalMemory / 1GB))
    Get-CimInstance Win32_PhysicalMemory -ErrorAction Stop | ForEach-Object {
        Add-Text ("شريحة: {0:N1} GiB | السرعة: {1} MHz | السرعة المضبوطة: {2} MHz | النوع: {3} | الشركة: {4}" -f ($_.Capacity / 1GB), $_.Speed, $_.ConfiguredClockSpeed, $_.SMBIOSMemoryType, $_.Manufacturer)
    }
} catch { Add-Text ('تعذر قراءة الذاكرة: ' + $_.Exception.Message) }

Add-Section 'محولات الرسوميات وتعريفاتها'
try {
    Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object {
        $vram = if ($_.AdapterRAM) { '{0:N2} GiB (قيمة WMI تقريبية؛ لا تعتمد وحدها)' -f ($_.AdapterRAM / 1GB) } else { 'غير معلومة من WMI' }
        Add-Text ("المحول: {0} | ذاكرة WMI: {1} | التعريف: {2} | تاريخ التعريف: {3} | الدقة الحالية: {4}x{5}" -f $_.Name, $vram, $_.DriverVersion, $_.DriverDate, $_.CurrentHorizontalResolution, $_.CurrentVerticalResolution)
    }
} catch { Add-Text ('تعذر قراءة محولات الرسوميات: ' + $_.Exception.Message) }

Add-Section 'NVIDIA وCUDA'
$nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidia) {
    try {
        Add-Text (& $nvidia.Source '--query-gpu=name,memory.total,memory.used,driver_version,compute_cap,utilization.gpu,temperature.gpu,power.draw' '--format=csv,noheader')
        Add-Text 'إصدار CUDA الذي يعلنه التعريف:'
        Add-Text ((& $nvidia.Source) | Select-String 'CUDA Version' | ForEach-Object { $_.Line.Trim() })
    } catch { Add-Text ('تعذر تشغيل nvidia-smi: ' + $_.Exception.Message) }
} else { Add-Text 'nvidia-smi غير موجود في PATH؛ لم يُثبت شيء.' }
$nvcc = Get-Command nvcc -ErrorAction SilentlyContinue
if ($nvcc) { try { Add-Text ((& $nvcc.Source '--version' 2>&1) | Select-Object -Last 4) } catch { Add-Text ('تعذر تشغيل nvcc: ' + $_.Exception.Message) } }
else { Add-Text 'مترجم CUDA nvcc غير موجود في PATH؛ وجود تعريف NVIDIA لا يعني أن CUDA Toolkit مثبت.' }

Add-Section 'أدوات Intel/OpenCL/SYCL المتاحة'
foreach ($toolName in @('sycl-ls', 'clinfo', 'ocloc', 'dpcpp')) {
    $tool = Get-Command $toolName -ErrorAction SilentlyContinue
    if ($tool) { Add-Text ("متاح: {0}" -f $toolName) } else { Add-Text ("غير موجود في PATH: {0}" -f $toolName) }
}

Add-Section 'Python ومكتبات معالجة الصور/التعلم المحلي'
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if ($python) {
    $pythonProbe = @'
import importlib.metadata as md, importlib.util, platform, struct
print(f"Python: {platform.python_version()} | {struct.calcsize('P')*8}-bit | {platform.python_implementation()}")
packages = ['numpy','Pillow','opencv-python','opencv-contrib-python','torch','torchvision','onnxruntime','onnxruntime-gpu','diffusers','transformers','accelerate','safetensors','scikit-image','scipy','cairosvg','skia-python','pycairo','cupy-cuda12x','openvino','intel-extension-for-pytorch']
for name in packages:
    try: print(f"{name}: {md.version(name)}")
    except md.PackageNotFoundError: pass
try:
    import torch
    print(f"PyTorch CUDA available: {torch.cuda.is_available()}")
    print(f"PyTorch CUDA build: {torch.version.cuda}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()): print(f"PyTorch device {i}: {torch.cuda.get_device_name(i)} | VRAM {torch.cuda.get_device_properties(i).total_memory/1024**3:.2f} GiB")
except Exception as e: print(f"PyTorch runtime probe: {type(e).__name__}: {e}")
try:
    import onnxruntime as ort
    print('ONNX Runtime providers: ' + ', '.join(ort.get_available_providers()))
except Exception as e: print(f"ONNX Runtime probe: {type(e).__name__}: {e}")
try:
    import cv2
    info=cv2.getBuildInformation()
    print('OpenCV CUDA build: ' + ('YES' if 'NVIDIA CUDA:                   YES' in info else 'not detected in build info'))
except Exception as e: print(f"OpenCV runtime probe: {type(e).__name__}: {e}")
'@
    try { Add-Text ($pythonProbe | & $python.Source - 2>&1) } catch { Add-Text ('تعذر فحص Python: ' + $_.Exception.Message) }
} else { Add-Text 'لم يُعثر على python أو py في PATH.' }

Add-Section 'أقراص التخزين (الموديل والسعة فقط)'
try {
    Get-CimInstance Win32_DiskDrive -ErrorAction Stop | ForEach-Object {
        Add-Text ("{0} | {1:N1} GB | الواجهة: {2} | الوسيط: {3}" -f $_.Model, ($_.Size / 1GB), $_.InterfaceType, $_.MediaType)
    }
} catch { Add-Text ('تعذر قراءة الأقراص: ' + $_.Exception.Message) }

$desktop = [Environment]::GetFolderPath('Desktop')
if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = $env:TEMP }
$outFile = Join-Path $desktop 'masar-hardware-report.txt'
$report | Set-Content -LiteralPath $outFile -Encoding UTF8
$report
Write-Output ''
Write-Output ('حُفظ التقرير في: ' + $outFile)
Write-Output 'أرسل محتوى التقرير النصي هنا. إذا ظهر مسار مستخدم أو معلومة لا تريد مشاركتها، احذفها قبل الإرسال.'
