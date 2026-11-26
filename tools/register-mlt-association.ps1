param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [switch]$Undo
)

$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
$backup = Join-Path $Root 'appdata\mlt-association-backup.json'
$classes = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Classes')
$entries = @(
    @{ Key = '.mlt'; Name = ''; Value = 'letitedit.Project' },
    @{ Key = '.mlt\OpenWithProgids'; Name = 'Shotcut.mlt'; Value = '' },
    @{ Key = '.mlt\OpenWithProgids'; Name = 'letitedit.Project'; Value = '' },
    @{ Key = 'letitedit.Project'; Name = ''; Value = 'letitedit project' },
    @{ Key = 'letitedit.Project\DefaultIcon'; Name = ''; Value = ('"{0}\assets\letitedit.ico",0' -f $Root) },
    # Without these, Windows' "Open with" list names the program after wscript.exe ("Windows Based Script Host").
    @{ Key = 'letitedit.Project\shell\open'; Name = 'FriendlyAppName'; Value = 'letitedit' },
    @{ Key = 'letitedit.Project\Application'; Name = 'ApplicationName'; Value = 'letitedit' },
    @{ Key = 'letitedit.Project\Application'; Name = 'ApplicationIcon'; Value = ('"{0}\assets\letitedit.ico",0' -f $Root) },
    @{ Key = 'letitedit.Project\shell\open\command'; Name = ''; Value = ('"{0}\System32\wscript.exe" "{1}\Open letitedit.vbs" "%1"' -f $env:SystemRoot, $Root) }
)
try {
    if ($Undo) {
        if (-not (Test-Path -LiteralPath $backup)) { throw "No association backup at $backup" }
        $saved = Get-Content -LiteralPath $backup -Raw | ConvertFrom-Json
        if ($saved.Root -ne $Root) { throw 'Association backup belongs to another folder' }
        foreach ($entry in $saved.Entries) {
            $key = $classes.OpenSubKey($entry.Key, $true)
            if ($null -eq $key) { continue }
            try {
                if ($key.GetValue($entry.Name, $null) -cne $entry.Value) { continue }
                if ($entry.Existed) {
                    $kind = [Microsoft.Win32.RegistryValueKind]$entry.Kind
                    $previous = $entry.Previous
                    switch ($kind.ToString()) {
                        'None' { $previous = [byte[]]@($entry.Previous) }
                        'Binary' { $previous = [byte[]]@($entry.Previous) }
                        'MultiString' { $previous = [string[]]@($entry.Previous) }
                        'DWord' { $previous = [int]$entry.Previous }
                        'QWord' { $previous = [long]$entry.Previous }
                    }
                    $key.SetValue($entry.Name, $previous, $kind)
                } else {
                    $key.DeleteValue($entry.Name, $false)
                }
            } finally { $key.Dispose() }
        }
        foreach ($path in @($saved.CreatedKeys | Sort-Object Length -Descending)) {
            $key = $classes.OpenSubKey($path)
            if ($null -eq $key) { continue }
            $empty = $key.ValueCount -eq 0 -and $key.SubKeyCount -eq 0
            $key.Dispose()
            if ($empty) { $classes.DeleteSubKey($path, $false) }
        }
        Remove-Item -LiteralPath $backup
    } else {
        foreach ($file in @('Open letitedit.vbs', 'assets\letitedit.ico')) {
            if (-not (Test-Path -LiteralPath (Join-Path $Root $file))) { throw "Missing $file" }
        }
        $choice = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mlt\UserChoice')
        if ($null -ne $choice) {
            try {
                if ($choice.GetValue('ProgId') -ne 'letitedit.Project') {
                    Write-Warning 'Windows already has a protected default for .mlt. Registration will not replace it; choose letitedit in Default apps. UserChoice was not changed.'
                }
            } finally { $choice.Dispose() }
        }
        if (-not (Test-Path -LiteralPath $backup)) {
            $created = @()
            foreach ($entry in $entries) {
                $parts = $entry.Key.Split('\')
                for ($index = 1; $index -le $parts.Count; $index++) {
                    $path = $parts[0..($index - 1)] -join '\'
                    $key = $classes.OpenSubKey($path)
                    if ($null -eq $key) { $created += $path } else { $key.Dispose() }
                }
                $key = $classes.OpenSubKey($entry.Key)
                $entry.Existed = $null -ne $key -and $entry.Name -in $key.GetValueNames()
                if ($entry.Existed) {
                    $entry.Previous = $key.GetValue($entry.Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                    $entry.Kind = [int]$key.GetValueKind($entry.Name)
                }
                if ($null -ne $key) { $key.Dispose() }
            }
            New-Item -ItemType Directory -Path (Split-Path $backup) -Force | Out-Null
            @{ Root = $Root; Entries = $entries; CreatedKeys = @($created | Select-Object -Unique) } |
                ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $backup -Encoding UTF8
        } else {
            $saved = Get-Content -LiteralPath $backup -Raw | ConvertFrom-Json
            if ($saved.Root -ne $Root) { throw 'Association backup belongs to another folder' }
        }
        foreach ($entry in $entries) {
            $key = $classes.CreateSubKey($entry.Key)
            try { $key.SetValue($entry.Name, $entry.Value, [Microsoft.Win32.RegistryValueKind]::String) }
            finally { $key.Dispose() }
        }
    }
} finally { $classes.Dispose() }
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class LetItEditAssociations { [DllImport("shell32.dll")] public static extern void SHChangeNotify(uint eventId, uint flags, IntPtr first, IntPtr second); }'
[LetItEditAssociations]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Output $(if ($Undo) { 'Restored previous per-user .mlt association.' } else { 'Registered per-user .mlt association for letitedit.' })
