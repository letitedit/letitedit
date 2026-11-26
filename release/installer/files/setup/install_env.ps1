# letitedit: builds the tool server's Python environment inside the install folder (run by the installer; safe to
# run again to repair). Everything goes under <App>: Python itself in <App>\python, the packages in <App>\env.
# Nothing is written to the person's own Python, PATH or registry (uv --no-registry --no-bin, no uv config files).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File <App>\setup\install_env.ps1 -App <App>
#
# Packages: <App>\setup\env\requirements-bridge.txt then requirements-bridge-nodeps.txt (--no-deps), the same lists
# as release\env in letitedit's source folder (no AGPL packages). Log: <App>\setup\install-env.log
# -Repair (the Start menu's Repair): also fits the tools to the folder afterwards, because the installer's own later step may never have finished.
param([Parameter(Mandatory = $true)][string]$App, [string]$PythonVersion = '3.14.7', [switch]$Repair)
$ErrorActionPreference = 'Stop'
$setup = Join-Path $App 'setup'
$log = Join-Path $setup 'install-env.log'
$uv = Join-Path $setup 'uv\uv.exe'
$envDir = Join-Path $App 'env'
$py = Join-Path $envDir 'Scripts\python.exe'
$env:UV_NO_CONFIG = '1'
$env:UV_CACHE_DIR = Join-Path $setup 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $App 'python'
$env:UV_PYTHON_BIN_DIR = Join-Path $App 'python\bin'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_LINK_MODE = 'copy'
$env:UV_NO_PROGRESS = '1'
$env:PYTHONUTF8 = '1'
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue

function Say($text) { Write-Host $text; Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format s), $text) -Encoding utf8 }
function Run($what, [string[]]$argv, [switch]$MayFail) {
    Add-Content -LiteralPath $log -Value ("> uv " + ($argv -join ' ')) -Encoding utf8
    $ErrorActionPreference = 'Continue'      # uv writes progress to stderr
    $out = & $uv @argv 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $out | ForEach-Object { "$_" } | Add-Content -LiteralPath $log -Encoding utf8
    if ($code -ne 0 -and $MayFail) { Add-Content -LiteralPath $log -Value "(uv exit $code; checked below)" -Encoding utf8; return }
    if ($code -ne 0) { Say "FAILED: $what (see $log)"; exit 1 }
}

Set-Content -LiteralPath $log -Value "letitedit environment build $(Get-Date -Format s) in $App" -Encoding utf8
Say "letitedit is setting up its Python tools. This needs the internet and takes a few minutes."
Say "Step 1 of 4: getting Python $PythonVersion (about 30 MB)..."
# uv also makes a 'cpython-3.14-...' junction; where Windows refuses to follow junctions (os error 448) that step
# fails after Python itself is in place, so the exact version's folder is used directly.
Run 'Python download' @('python', 'install', $PythonVersion, '--no-bin', '--no-registry') -MayFail
$base = Get-ChildItem -LiteralPath (Join-Path $App 'python') -Directory -Filter "cpython-$PythonVersion-*" -ErrorAction SilentlyContinue |
    Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } | ForEach-Object { Join-Path $_.FullName 'python.exe' } |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $base) { Say "FAILED: Python $PythonVersion did not arrive (see $log)"; exit 1 }
# Microsoft's C++ runtime: onnxruntime, ctranslate2 (speech to text) and espeak-ng can't load without it, and a clean
# Windows lacks it. When Windows lacks it (or has one too old), Microsoft's own installer, which setup carries, runs once
# with Windows' admin prompt; nothing changes on a PC that has it (bridge\letitedit\core\vc_runtime.py).
$ErrorActionPreference = 'Continue'
$vcPy = Join-Path $App 'bridge\letitedit\core\vc_runtime.py'
$vcCheck = (& $base -I $vcPy --check 2>$null) -join '' | ConvertFrom-Json
if ($vcCheck -and $vcCheck.needed) { Say "Microsoft's C++ runtime is missing: installing it (Windows asks once for an administrator's OK)..." }
$vc = & $base -I $vcPy --ensure $App 2>&1
$vcCode = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
Add-Content -LiteralPath $log -Value ("C++ runtime: " + ($vc -join ' ')) -Encoding utf8
if ($vcCode -ne 0) {
    $why = ''
    $json = $vc | ForEach-Object { "$_" } | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -Last 1
    if ($json) { try { $why = ($json | ConvertFrom-Json).error } catch { $why = '' } }
    Say "FAILED: Microsoft's C++ runtime, which this PC lacks, isn't installed. $why"; exit 1
}
if (Test-Path -LiteralPath $envDir) { Say "Replacing the old tool environment..."; Remove-Item -LiteralPath $envDir -Recurse -Force }
# Python's own venv (its python.exe reads pyvenv.cfg), not uv venv (whose launcher has the junction path built in).
$ErrorActionPreference = 'Continue'
$vout = & $base -I -m venv --without-pip $envDir 2>&1
$ErrorActionPreference = 'Stop'
"$vout" | Add-Content -LiteralPath $log -Encoding utf8
if (-not (Test-Path -LiteralPath $py)) { Say "FAILED: could not make the tool environment (see $log)"; exit 1 }
# The environment must name the exact Python folder, not uv's 'cpython-3.14-...' junction: some programs (and
# sandboxes) refuse to follow junctions. The junction itself is removed (only the link, never its target).
$cfg = Join-Path $envDir 'pyvenv.cfg'
$lines = [IO.File]::ReadAllLines($cfg) | ForEach-Object { if ($_ -match '^home\s*=') { 'home = ' + (Split-Path -Parent $base) } else { $_ } }
[IO.File]::WriteAllLines($cfg, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
Get-ChildItem -LiteralPath (Join-Path $App 'python') -Directory -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
    ForEach-Object { [IO.Directory]::Delete($_.FullName, $false) }
Say "Step 2 of 4: getting the packages letitedit's tools use (about 300 MB)..."
Run 'packages' @('pip', 'install', '--python', $py, '-r', (Join-Path $setup 'env\requirements-bridge.txt'))
Say "Step 3 of 4: two speech packages..."
Run 'speech packages' @('pip', 'install', '--python', $py, '--no-deps', '-r', (Join-Path $setup 'env\requirements-bridge-nodeps.txt'))
Say "Step 4 of 4: checking..."
$ErrorActionPreference = 'Continue'
& $uv pip freeze --python $py 2>$null | Set-Content -LiteralPath (Join-Path $envDir 'installed-packages.txt') -Encoding utf8
& $py -I (Join-Path $setup 'env\licence_scan.py') (Join-Path $envDir 'licences.tsv') 2>&1 | Tee-Object -Variable scan | Out-Null
"$scan" | Add-Content -LiteralPath $log -Encoding utf8
if ($LASTEXITCODE -ne 0) { Say "FAILED: an AGPL package is in the environment: $scan"; exit 1 }
$check = & $py -I -c "import mcp, numpy, scipy, PIL, pillow_heif, cv2, onnxruntime, fontTools, yaml, soundfile, faster_whisper, kokoro_onnx, huggingface_hub, tkinter; print('imports OK')" 2>&1
"$check" | Add-Content -LiteralPath $log -Encoding utf8
if ($LASTEXITCODE -ne 0) { Say "FAILED: the tools' packages do not load: $check"; exit 1 }
if (Test-Path -LiteralPath $env:UV_CACHE_DIR) { Remove-Item -LiteralPath $env:UV_CACHE_DIR -Recurse -Force -ErrorAction SilentlyContinue }
Set-Content -LiteralPath (Join-Path $envDir 'letitedit-env.ok') -Value (Get-Date -Format s) -Encoding ascii
if ($Repair) {
    Say "Fitting the tools to this folder..."
    $fit = Start-Process -FilePath $py -ArgumentList @('-I', "`"$(Join-Path $setup 'relocate.py')`"", "`"$App`"") -WindowStyle Hidden -PassThru
    $null = $fit.Handle      # or its exit code can't be read after
    if (-not $fit.WaitForExit(3600000)) { $fit.Kill(); Say "FAILED: fitting the tools got stuck. Restart your PC and run the letitedit installer again."; exit 1 }
    if ($fit.ExitCode -ne 0) { Say "FAILED: the tools could not be fitted to this folder (see $(Join-Path $setup 'relocated.json'))"; exit 1 }
}
Say "Done: the tool environment is ready."
# T368: a setup that went wrong earlier left a note for the editor's problem report; it is fixed now
Remove-Item -LiteralPath (Join-Path $setup 'setup-problem.json') -Force -ErrorAction SilentlyContinue
exit 0
