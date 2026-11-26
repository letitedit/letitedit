# Build letitedit and stage it side by side: app\letitedit-YYYYMMDD.N.exe (never overwrites a running build), and the QML and
# share files the editor reads at run time are refreshed. The new build then really starts and closes on the private test
# desktop (tools\journey-checks\check_new_build.py), and this stops with an error if it doesn't. Never stops an editor or
# discards unsaved work. Build threads are capped (one heavy job at a time).
#
# The launcher doesn't move on a build: app\ai-assist-executable.txt (what the launcher, the AI's open and the installer use)
# moves only with -Promote, once the journeys for that work have passed on that exact exe. A build carries everything in the
# shared src\ tree, anyone's unfinished work included, and four times moving on every build put unproved work in front of the
# owner (T31's .11 that crashed at start, T53's .9, T74's .22, T97's .31).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\LetItEdit\build.ps1 [-Jobs 4] [-NoBuild]
#   ... build.ps1 -Promote C:\LetItEdit\app\letitedit-YYYYMMDD.N.exe    start check, then the launcher moves to that exe
param([int]$Jobs = 4, [switch]$NoBuild, [string]$Promote = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $root 'src'
$app = Join-Path $root 'app'
if (-not $NoBuild -and -not $Promote) {
    $env:MSYSTEM = 'MINGW64'
    $cmd = "(cd '$($src -replace '\\','/' -replace '^C:','/c')' && cmake -S . -B build/release -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSHOTCUT_VERSION=26.9.27 && cmake --build build/release -j $Jobs) > '$($root -replace '\\','/' -replace '^C:','/c')/build.log' 2>&1"
    & C:\msys64\usr\bin\bash.exe -lc $cmd
    if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $root 'build.log') -Tail 30; throw 'Build failed' }
}
if ($Promote) {
    $exe = $Promote
} else {
    $day = Get-Date -Format 'yyyyMMdd'
    $n = 1
    while (Test-Path (Join-Path $app "letitedit-$day.$n.exe")) { $n++ }
    $exe = Join-Path $app "letitedit-$day.$n.exe"
    & C:\msys64\mingw64\bin\strip.exe -o $exe (Join-Path $src 'build\release\src\shotcut.exe')
    if ($LASTEXITCODE -ne 0) { throw 'strip failed' }
    # a running editor holds this DLL open (it is the same file): that is no reason to stop a build (T80)
    try { Copy-Item (Join-Path $src 'third_party\webview2\x64\WebView2Loader.dll') (Join-Path $app 'WebView2Loader.dll') -Force -ErrorAction Stop }
    catch { Write-Output 'WebView2Loader.dll is in use by a running editor, left as it is' }
    # run-time files the editor reads from app\share (QML views, filters, elements) follow the source
    robocopy (Join-Path $src 'src\qml') (Join-Path $app 'share\shotcut\qml') /E /NFL /NDL /NJH /NJS /NP | Out-Null
    # elements: new and changed files only (sounds removed from the source are deleted from app\ by hand)
    robocopy (Join-Path $src 'elements') (Join-Path $app 'share\shotcut\elements') /E /NFL /NDL /NJH /NJS /NP | Out-Null
}
# The launcher never points at a build that doesn't start. PowerShell mustn't stop on the check's own output.
$pointer = Join-Path $app 'ai-assist-executable.txt'
$check = Join-Path $root 'tools\journey-checks\check_new_build.py'
$ErrorActionPreference = 'Continue'
$said = & python $check $exe 2>&1 | ForEach-Object { "$_" }
$checkExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($checkExit -eq 0) { $said | Select-Object -Last 3 | Write-Output }
if ($checkExit -ne 0) {
    # the whole check output, never only its last lines (a busy PC once refused three good builds and the reason was lost);
    # check_new_build.py also keeps its reason in app\start-check-last.txt
    $said | Write-Output
    $why = Join-Path $app 'start-check-last.txt'
    if (Test-Path $why) { Get-Content $why | Write-Output }
    $kept = if (Test-Path $pointer) { Get-Content $pointer -Raw } else { '(none)' }
    Write-Output "$exe failed its start check. The launcher stays on: $kept"
    throw "The new build $exe failed its start check; ai-assist-executable.txt was not changed."
}
if ($Promote) {
    [IO.File]::WriteAllText($pointer, $exe, (New-Object Text.UTF8Encoding $false))
    Write-Output "The launcher is now on $exe, start check passed (older builds and open windows untouched)."
} else {
    $kept = if (Test-Path $pointer) { (Get-Content $pointer -Raw).Trim() } else { '(none)' }
    Write-Output "Staged $exe, start check passed. The launcher stays on $kept."
    Write-Output "Run the journeys on this exe, then: build.ps1 -Promote $exe"
}
# the engine's patched text and captions modules (engine-patches\README.md): swapped into app\lib\mlt when no window or
# export has them loaded (backup kept); otherwise it says so and leaves them for engine-patches\deploy.ps1
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'engine-patches\deploy.ps1') -App $app -IfFree
