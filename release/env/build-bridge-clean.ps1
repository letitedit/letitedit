# Builds a fresh, clean Python environment for the letitedit tool server (bridge) at C:\LetItEdit\envs\bridge-clean
# (or -Target). Only the packages the bridge imports (requirements-bridge.txt + requirements-bridge-nodeps.txt);
# nothing from the person's global Python is copied, and the global Python is not changed (venv only).
#
#   powershell -ExecutionPolicy Bypass -File C:\LetItEdit\release\env\build-bridge-clean.ps1 [-Python <python.exe>] [-Target <dir>]
#
# Afterwards: <Target>\Scripts\python.exe C:\LetItEdit\bridge\letitedit_mcp.py is the tool server.
# Writes <Target>\installed-packages.txt (pip freeze) and <Target>\licences.tsv (name, version, licence per package).
# An existing Target is refused (never overwritten or deleted): pass a new -Target or remove it by hand first.
param(
    [string]$Python = '',
    [string]$Target = 'C:\LetItEdit\envs\bridge-clean'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Python) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $Python = (& py -3.14 -c 'import sys; print(sys.executable)').Trim() }
    if (-not $Python) { $Python = (Get-Command python).Source }
}
$ver = (& $Python -c 'import sys; print(*sys.version_info[:2], sep=chr(46))').Trim()
if ($ver -ne '3.14') { Write-Warning "Python $ver (tested with 3.14)" }
if (Test-Path -LiteralPath $Target) { throw "$Target already exists; choose another -Target (nothing was changed)" }

& $Python -m venv $Target
if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
$py = Join-Path $Target 'Scripts\python.exe'
& $py -m pip install --disable-pip-version-check --no-input --upgrade pip
& $py -m pip install --disable-pip-version-check --no-input -r (Join-Path $here 'requirements-bridge.txt')
if ($LASTEXITCODE -ne 0) { throw 'stage 1 install failed' }
& $py -m pip install --disable-pip-version-check --no-input --no-deps -r (Join-Path $here 'requirements-bridge-nodeps.txt')
if ($LASTEXITCODE -ne 0) { throw 'stage 2 install failed' }

& $py -m pip freeze --all | Set-Content -Encoding utf8 (Join-Path $Target 'installed-packages.txt')
& $py -I (Join-Path $here 'licence_scan.py') (Join-Path $Target 'licences.tsv')
# Every module the bridge imports must load (fails loudly otherwise).
& $py -I -c "import mcp, numpy, scipy, PIL, pillow_heif, cv2, onnxruntime, fontTools, yaml, soundfile, faster_whisper, kokoro_onnx, huggingface_hub; print('imports OK; onnxruntime providers:', onnxruntime.get_available_providers())"
if ($LASTEXITCODE -ne 0) { throw 'import check failed' }
Write-Output "Built $Target"
