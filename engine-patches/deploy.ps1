# Deploys letitedit's patched engine files from engine-patches\modules into the app:
#   libmltqt6.dll, libmltplus.dll  (built by build_modules.sh)  -> app\lib\mlt   (the engine's modules)
#   libmltresample.dll             (built by mlt-resample-close\build_resample.sh) -> app\lib\mlt
#   libmlt-7.dll                   (built by mlt-chain-normalizer-ref\build_libmlt.sh) -> app   (the engine itself,
#                                  shared by the editor and melt.exe)
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\LetItEdit\engine-patches\deploy.ps1 [-App C:\LetItEdit\app]
#       [-NoCheck] [-IfFree] [-Undo <backup folder>]
#
# 1. The files must match modules\SHA256SUMS.txt (exit 4 if not, or not built) and be listed in modules\VERIFIED.txt,
#    which only a full pass of check_engine.py writes (exit 3 if not): files that have not passed every engine check
#    are never deployed, by hand or by an editor build.
# 2. Windows locks a loaded DLL, and every open letitedit window and running export (melt) has these files loaded.
#    While any process has one of them open, nothing is changed: the script names the processes and stops (exit 2).
#    It never closes a window or stops an export.
# 3. The files it replaces are kept in engine-patches\backup-<yyyyMMdd-HHmmss>\ (with their SHA-256).
# 4. It swaps the files, then runs check_engine.py on the app under the PC render lock. A failed check puts the
#    backup back (exit 1).
#
# -NoCheck  skip step 4 (the files were verified in step 1)
# -IfFree   for build scripts (build.ps1): when the files are already deployed, not built, not verified or in use,
#           say so and exit 0; otherwise swap them (steps 1-3, no step 4)
# -Undo     put a backup folder's files back (the same in-use rule; no render check). A backup holds the files it
#           lists in its SHA256SUMS (backups made before libmlt-7.dll was deployed hold only the two modules).
param(
    [string]$App = '',
    [switch]$NoCheck,
    [switch]$IfFree,
    [string]$Undo = ''
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
if (-not $App) { $App = Join-Path $root 'app' }
$mltDir = Join-Path $App 'lib\mlt'
$modules = Join-Path $here 'modules'
# each file and the folder of the app it goes into
$dest = [ordered]@{ 'libmltqt6.dll' = $mltDir; 'libmltplus.dll' = $mltDir; 'libmltresample.dll' = $mltDir; 'libmlt-7.dll' = $App }
$names = @($dest.Keys)

function Target([string]$n) { Join-Path $dest[$n] $n }

function Hash([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() }

function Expected([string]$folder) {
    # name -> sha256 from a SHA256SUMS file ("<hash> *<name>" or "<hash>  <name>")
    $sums = @{}
    $file = Get-ChildItem -LiteralPath $folder -Filter 'SHA256SUMS*' | Select-Object -First 1
    if (-not $file) { throw "no SHA256SUMS file in $folder" }
    foreach ($line in Get-Content -LiteralPath $file.FullName) {
        if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$') { $sums[$Matches[2].Trim()] = $Matches[1].ToLower() }
    }
    $sums
}

function Users([string]$path) {
    # processes that have the file loaded (their module list) - best effort, for the message
    $full = (Resolve-Path -LiteralPath $path).Path
    Get-Process | ForEach-Object {
        $p = $_
        try {
            if ($p.Modules | Where-Object { $_.FileName -ieq $full }) {
                '{0} (pid {1}){2}' -f $p.ProcessName, $p.Id, $(if ($p.MainWindowTitle) { ": $($p.MainWindowTitle)" } else { '' })
            }
        } catch { }
    }
}

function InUse([string]$path) {
    # a loaded DLL cannot be opened for writing: the definitive test before a swap
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    try { $f = [IO.File]::Open($path, 'Open', 'ReadWrite', 'None'); $f.Close(); return $false } catch { return $true }
}

function StopIfInUse([string[]]$which) {
    $busy = @($which | Where-Object { InUse (Target $_) })
    if (-not $busy) { return }
    $who = @($busy | ForEach-Object { Users (Target $_) } | Sort-Object -Unique)
    $msg = "In use, nothing changed: $($busy -join ', ') in $App is loaded by " +
           $(if ($who) { $who -join '; ' } else { 'another process' }) +
           ". Close the letitedit windows (and let exports finish), then run this script again."
    if ($IfFree) { Write-Output "engine files: $msg"; exit 0 }
    Write-Output $msg
    exit 2
}

function Swap([string]$from, [string]$backup, [string[]]$which) {
    New-Item -ItemType Directory -Force $backup | Out-Null
    $lines = foreach ($n in $which) {
        $dst = Target $n
        if (Test-Path -LiteralPath $dst) {
            Copy-Item -LiteralPath $dst (Join-Path $backup $n)
            '{0} *{1}' -f (Hash $dst), $n
        }
    }
    # SHA256SUMS without an extension: backups stay out of git (.gitignore versions only text and code files)
    [IO.File]::WriteAllLines((Join-Path $backup 'SHA256SUMS'), [string[]]$lines)
    try {
        foreach ($n in $which) { Copy-Item -LiteralPath (Join-Path $from $n) (Target $n) -Force }
    } catch {
        # a process loaded a file between the in-use test and the copy: put back whatever was copied
        foreach ($n in $which) {
            if (Test-Path -LiteralPath (Join-Path $backup $n)) {
                Copy-Item -LiteralPath (Join-Path $backup $n) (Target $n) -Force -ErrorAction SilentlyContinue
            }
        }
        throw "the copy into $App failed ($($_.Exception.Message)); the previous files were put back"
    }
}

if (-not (Test-Path -LiteralPath $mltDir)) { throw "no engine folder at $mltDir" }

if ($Undo) {
    $sums = Expected $Undo
    $back = @($names | Where-Object { $sums.ContainsKey($_) })
    if (-not $back) { throw "$Undo lists none of $($names -join ', ') in its SHA256SUMS" }
    foreach ($n in $back) {
        if ((Hash (Join-Path $Undo $n)) -ne $sums[$n]) { throw "$Undo\$n does not match its SHA256SUMS" }
    }
    StopIfInUse $back
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Swap $Undo (Join-Path $here "backup-$stamp") $back
    Write-Output "Put back $($back -join ', ') from $Undo (the ones it replaced are in engine-patches\backup-$stamp)."
    exit 0
}

function Skip([string]$msg, [int]$code) {
    # -IfFree (editor builds): say why and carry on; otherwise stop with the code
    Write-Output "engine files: $msg"
    if ($IfFree) { exit 0 }
    exit $code
}

$missing = @($names | Where-Object { -not (Test-Path -LiteralPath (Join-Path $modules $_)) })
if ($missing -or -not (Test-Path -LiteralPath (Join-Path $modules 'SHA256SUMS.txt'))) {
    Skip ("$($missing -join ', ') not built here ($modules); run build_modules.sh (the modules) and " +
          'mlt-cache-held-item\build_libmlt.sh (libmlt-7.dll) and mlt-resample-close\build_resample.sh (libmltresample.dll) first. Nothing deployed.') 4
}
$want = Expected $modules
$bad = @($names | Where-Object { (Hash (Join-Path $modules $_)) -ne $want[$_] })
if ($bad) { Skip "$($bad -join ', ') in $modules do not match modules\SHA256SUMS.txt. Nothing deployed." 4 }
# only files that passed every engine check (check_engine.py writes modules\VERIFIED.txt after a full pass)
$verified = New-Object 'System.Collections.Generic.HashSet[string]'
$vfile = Join-Path $modules 'VERIFIED.txt'
if (Test-Path -LiteralPath $vfile) {
    foreach ($line in Get-Content -LiteralPath $vfile) {
        if ($line -match '^([0-9a-fA-F]{64})\s+\*?(\S+)') { [void]$verified.Add($Matches[1].ToLower() + ' ' + $Matches[2]) }
    }
}
$unverified = @($names | Where-Object { -not $verified.Contains($want[$_] + ' ' + $_) })
if ($unverified) {
    Skip ("$($unverified -join ', ') in $modules have not passed check_engine.py, so nothing was deployed. Copy " +
          'them into a copy of the app and run check_engine.py on that copy: a full pass records them in ' +
          'modules\VERIFIED.txt.') 3
}
$current = @($names | Where-Object { -not (Test-Path -LiteralPath (Target $_)) -or (Hash (Target $_)) -ne $want[$_] })
if (-not $current) {
    Write-Output "engine files: already deployed in $App ($($names -join ', '))"
    exit 0
}
StopIfInUse $names

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $here "backup-$stamp"
Swap $modules $backup $current
foreach ($n in $names) {
    if ((Hash (Target $n)) -ne $want[$n]) { throw "copy of $n did not land (hash differs)" }
}
Write-Output "Deployed $($current -join ', ') to $App; the replaced files are in $backup."

if ($NoCheck -or $IfFree) { exit 0 }
$lock = Join-Path $root 'bridge\render_lock.py'
$check = Join-Path $here 'check_engine.py'
$frames = Join-Path $backup 'check-frames'
# the PC render lock (waits its turn up to an hour); the checks are a few minutes of single-frame renders
& python $lock run --name 'engine deploy check' --timeout-s 3600 -- python $check --app $App --out $frames
if ($LASTEXITCODE -ne 0) {
    Write-Output "The engine checks failed or did not run (exit $LASTEXITCODE, frames in $frames): putting the previous files back."
    if (@($current | Where-Object { InUse (Target $_) })) {
        Write-Output "Could not put them back: a process loaded the new files meanwhile. Run: deploy.ps1 -Undo $backup"
        exit 1
    }
    foreach ($n in $current) {
        if (Test-Path -LiteralPath (Join-Path $backup $n)) { Copy-Item -LiteralPath (Join-Path $backup $n) (Target $n) -Force }
    }
    exit 1
}
Write-Output 'Engine checks passed on the deployed files.'
