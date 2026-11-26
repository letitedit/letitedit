# Run once by setup, hidden, after the files are in place: the editor's libraries are mapped once and its QML read once,
# and the video engine loads every module (melt -query), so that the first time the person opens letitedit, Windows
# (and its antivirus, which checks each new file the first time it is used) doesn't do that work while they wait.
# Nothing is run from the libraries: each is mapped as an image resource and let go. A failure here changes nothing.
param([Parameter(Mandatory)][string]$App)
$ErrorActionPreference = 'Continue'
$t0 = Get-Date
Add-Type -Namespace LetItEdit -Name WarmUp -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern System.IntPtr LoadLibraryExW(string path, System.IntPtr file, uint flags);
[DllImport("kernel32.dll")]
public static extern bool FreeLibrary(System.IntPtr module);
'@
$appDir = Join-Path $App 'app'
$mapped = 0
$dlls = @(Get-ChildItem -LiteralPath $appDir -Filter '*.dll' -File -ErrorAction SilentlyContinue) +
        @(Get-ChildItem -LiteralPath (Join-Path $appDir 'lib') -Filter '*.dll' -File -Recurse -ErrorAction SilentlyContinue)
foreach ($dll in $dlls) {
    $h = [LetItEdit.WarmUp]::LoadLibraryExW($dll.FullName, [IntPtr]::Zero, 0x20)   # LOAD_LIBRARY_AS_IMAGE_RESOURCE
    if ($h -ne [IntPtr]::Zero) { [void][LetItEdit.WarmUp]::FreeLibrary($h); $mapped++ }
}
$read = 0
$buffer = New-Object byte[] 1048576
foreach ($dir in (Join-Path $appDir 'lib\qml'), (Join-Path $appDir 'share\shotcut\qml')) {
    foreach ($f in Get-ChildItem -LiteralPath $dir -File -Recurse -Include '*.qml', '*.js', 'qmldir' -ErrorAction SilentlyContinue) {
        try { $s = [IO.File]::OpenRead($f.FullName); while ($s.Read($buffer, 0, $buffer.Length) -gt 0) { }; $s.Dispose(); $read++ } catch { }
    }
}
$melt = Join-Path $appDir 'melt.exe'
$code = -1
if (Test-Path -LiteralPath $melt) {
    $p = Start-Process -FilePath $melt -ArgumentList '-query', 'filters' -WorkingDirectory $appDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $env:TEMP 'letitedit-warm-up.txt') -Wait
    $code = $p.ExitCode
}
$line = "warm-up: {0} libraries mapped, {1} QML files read, engine exit {2}, in {3:N1} s" -f $mapped, $read, $code, ((Get-Date) - $t0).TotalSeconds
Write-Output $line
Set-Content -LiteralPath (Join-Path $App 'setup\warm-up.log') -Value $line -Encoding UTF8
