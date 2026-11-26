# Builds the letitedit installer locally: out\letitedit-Setup-<version>.exe. Nothing is uploaded or published.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\LetItEdit\release\installer\build.ps1 [-Version 1.0.0]
#
# 1. models-manifest.json from every SOURCE.md (make_manifest.py; stops when a record does not check out).
# 2. The editor = the build named in app\ai-assist-executable.txt (the promoted one; older builds are left out), or with
#    -Exe letitedit-YYYYMMDD.N.exe a staged build in app\ (a candidate installer; nothing is promoted); the engine's
#    two patched modules come from engine-patches\modules (checked against its SHA256SUMS.txt); the motion engine's
#    Node (motion\node\node.exe, else the build PC's Node 22.12+) is staged in out\stage\node.
# 3. Inno Setup 6.7.3 (tools\innosetup, portable copy) compiles letitedit.iss.
# Tools: tools\innosetup (Inno Setup 6.7.3, jrsoftware.org, sha256 9c73c3ba...b732 of innosetup-6.7.3.exe) and
# tools\uv\uv.exe (uv 0.12.5, astral-sh/uv GitHub release, zip sha256 4c4d49d8...f39a); see tools\downloads.
param([string]$Version = '', [switch]$FileList, [string]$Exe = '')
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($FileList) {
    if ($Exe) { $env:LETITEDIT_INSTALLER_EXE = Split-Path -Leaf $Exe }
    & python -I (Join-Path $here 'file_list.py')
    if ($LASTEXITCODE -ne 0) { throw 'Installer file-list check failed; nothing was staged or compiled.' }
    return
}
$src = (Resolve-Path (Join-Path $here '..\..')).Path
$iscc = Join-Path $here 'tools\innosetup\ISCC.exe'
if ($Exe) { $exe = Split-Path -Leaf $Exe } else {
    $exe = Split-Path -Leaf (Get-Content -LiteralPath (Join-Path $src 'app\ai-assist-executable.txt') -Raw).Trim()
}
$env:LETITEDIT_INSTALLER_EXE = $exe   # file_list.py and check_private.py look at the same editor
if (-not (Test-Path -LiteralPath (Join-Path $src "app\$exe"))) { throw "editor build $exe not found in $src\app" }
if (-not $Version) { $Version = '1.0.0-' + ($exe -replace '^letitedit-(\d{8})\.(\d+)\.exe$', '$1.$2') }

Write-Host "1/3 model manifest"
& python -I (Join-Path $here 'make_manifest.py') --root $src --out (Join-Path $here 'models-manifest.json')
if ($LASTEXITCODE -ne 0) { throw 'make_manifest.py reported a problem (see CHECK lines)' }
& python -I (Join-Path $here 'check_assets.py') --root $src
if ($LASTEXITCODE -ne 0) { throw 'the asset library names files this source folder lacks; nothing was staged or compiled.' }

# Styles, Looks and skills ship only as git has them: a file there that git doesn't track (a draft a Learn or an
# import left behind, perhaps with frames of a private reference in it) stops the build. The legacy style-packs
# folder is not shipped at all (letitedit.iss) and is not looked at here.
$stray = @(& git -C $src status --porcelain --ignored --untracked-files=all -- looks skills |
           Where-Object { $_ -match '^(\?\?|!!) ' } | ForEach-Object { $_.Substring(3) } |
           Where-Object { $_ -notmatch '(^|/)__pycache__/|\.pyc$' })
if ($LASTEXITCODE -ne 0) { throw 'git status failed; nothing was staged or compiled.' }
if ($stray.Count) {
    $stray | Select-Object -First 20 | ForEach-Object { Write-Host "  not in git: $_" }
    throw "$($stray.Count) file(s) in looks or skills are not in git and would ship; move them out (or commit them if they are product files). Nothing was staged or compiled."
}

Write-Host "2/3 stage ($exe, version $Version)"
# the engine's patched text and captions modules (engine-patches\README.md) ship from engine-patches\modules, so a
# customer gets them even while this PC's own app\lib\mlt still holds the old ones (open windows lock them)
$modules = Join-Path $src 'engine-patches\modules'
$sums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $modules 'SHA256SUMS.txt') -ErrorAction SilentlyContinue) {
    if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$') { $sums[$Matches[2].Trim()] = $Matches[1].ToLower() }
}
$verified = @(Get-Content -LiteralPath (Join-Path $modules 'VERIFIED.txt') -ErrorAction SilentlyContinue |
              Where-Object { $_ -match '^[0-9a-fA-F]{64}\s' } | ForEach-Object { ($_ -split '\s+\*?')[0..1] -join ' ' })
foreach ($n in 'libmltqt6.dll', 'libmltplus.dll', 'libmltresample.dll', 'libmlt-7.dll') {
    $f = Join-Path $modules $n
    if (-not (Test-Path -LiteralPath $f) -or -not $sums[$n] -or (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower() -ne $sums[$n]) {
        throw "engine-patches\modules\$n is missing or does not match its SHA256SUMS.txt: build it with engine-patches\build_modules.sh"
    }
    if ($verified -notcontains "$($sums[$n]) $n") {
        throw "engine-patches\modules\$n has not passed engine-patches\check_engine.py (not in modules\VERIFIED.txt): check it on a copy of the app first"
    }
}
# Microsoft's C++ runtime installer, shipped as Microsoft signs it (setup runs it only on a PC without the runtime)
$vcRedist = Join-Path $here 'tools\vcredist\vc_redist.x64.exe'
if (-not (Test-Path -LiteralPath $vcRedist)) {
    throw "tools\vcredist\vc_redist.x64.exe is missing: download https://aka.ms/vc14/vc_redist.x64.exe (Microsoft's latest supported x64 redistributable) into it"
}
$vcSig = Get-AuthenticodeSignature -LiteralPath $vcRedist
if ($vcSig.Status -ne 'Valid' -or $vcSig.SignerCertificate.Subject -notmatch '^CN=Microsoft Corporation,') {
    throw "tools\vcredist\vc_redist.x64.exe is not validly signed by Microsoft ($($vcSig.Status), $($vcSig.SignerCertificate.Subject))"
}
$vcVersion = (Get-Item -LiteralPath $vcRedist).VersionInfo.FileVersion
if ([version]$vcVersion -lt [version]'14.40') { throw "tools\vcredist\vc_redist.x64.exe is $vcVersion; 14.40 or later is needed" }
Write-Host "   Microsoft C++ runtime installer $vcVersion"
$stage = Join-Path $here 'out\stage'
New-Item -ItemType Directory -Force $stage | Out-Null
# motion clips: the engine's npm packages (npm ci in motion\engine) and a Node 22.12+ to run them (motion\node\node.exe,
# else the build PC's Node); the installer ships no browser (the engine draws with the PC's own Edge or Chrome)
if (-not (Test-Path -LiteralPath (Join-Path $src 'motion\engine\node_modules\hyperframes\bin\hyperframes.mjs'))) {
    throw "the motion engine's packages are missing: cd $src\motion\engine; npm ci --ignore-scripts"
}
$node = Join-Path $src 'motion\node\node.exe'
if (-not (Test-Path -LiteralPath $node)) { $node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source }
if (-not $node) { throw 'no Node.js to ship with the motion engine: motion\node\node.exe or Node 22.12+ on PATH' }
$nodeVersion = (& $node --version).Trim()
if ([version]$nodeVersion.TrimStart('v') -lt [version]'22.12.0') { throw "Node $nodeVersion ($node) is older than 22.12" }
New-Item -ItemType Directory -Force (Join-Path $stage 'node') | Out-Null
Copy-Item -LiteralPath $node -Destination (Join-Path $stage 'node\node.exe') -Force
Write-Host "   Node $nodeVersion from $node"
# the Node that ships carries its own release's full LICENSE file (every library bundled in node.exe)
$nodeLicence = Get-Content -LiteralPath (Join-Path $src 'motion\LICENSE-node.txt') -Raw
if ($nodeLicence -notmatch "(?m)^Version: $([regex]::Escape($nodeVersion)) " -or $nodeLicence -notmatch 'located at deps/') {
    throw "motion\LICENSE-node.txt is not Node $nodeVersion's full LICENSE file: put https://github.com/nodejs/node/blob/$nodeVersion/LICENSE in it, below its Version line"
}
$marker = [ordered]@{ product = 'letitedit'; version = $Version; editor = $exe; built = (Get-Date -Format s);
                      python = '3.14.7'; uv = '0.12.5'; node = $nodeVersion; requirements = 'release\env\requirements-bridge*.txt' }
[IO.File]::WriteAllText((Join-Path $stage 'install-marker.json'), ($marker | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
# the Codex plugin's manifest names this PC's own Python: it ships with a neutral command (setup's relocate.py points
# it at the install's Python)
& python -I (Join-Path $here 'stage_plugin.py') (Join-Path $src 'codex\plugins\letitedit\.codex-plugin\plugin.json') (Join-Path $stage 'codex-plugin.json')
if ($LASTEXITCODE -ne 0) { throw 'stage_plugin.py failed; nothing was compiled.' }

# nothing private ships: no user folder, Drive or server path, none of the owner's names or keys, nothing from
# looks-library\, tests\ or the other never-shipped folders, in any file the installer would carry (check_private.py)
& python -I (Join-Path $here 'check_private.py')
if ($LASTEXITCODE -ne 0) { throw 'check_private.py found private data or a never-shipped file in what the installer would carry (BLOCK lines above); nothing was compiled.' }

Write-Host "3/3 compile"
& $iscc /Q "/DSrc=$src" "/DExe=$exe" "/DAppVersion=$Version" (Join-Path $here 'letitedit.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
$out = Join-Path $here "out\letitedit-Setup-$Version.exe"
$h = (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash.ToLower()
"{0}`t{1}`t{2}" -f (Split-Path -Leaf $out), (Get-Item $out).Length, $h | Set-Content -LiteralPath (Join-Path $here 'out\SHA256SUMS.txt') -Encoding ascii
Write-Host ("Built {0} ({1:N0} MB) sha256 {2}" -f $out, ((Get-Item $out).Length / 1MB), $h)
