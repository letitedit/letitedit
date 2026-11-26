param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$Project
)

$ErrorActionPreference = 'Stop'
$appdata = Join-Path $Root 'appdata'
$profilePattern = '(?i)(?:^|\s)--appdata\s+(?:"' + [regex]::Escape($appdata) + '"|' + [regex]::Escape($appdata) + '(?=\s|$))'
$owners = @()
try {
    $owners = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'letitedit-%.exe'" |
        Where-Object { $_.CommandLine -match $profilePattern } | Sort-Object CreationDate)
} catch { Write-Warning 'Could not inspect running editors; opening with normal appdata.' }
$recordRoots = @((Join-Path $Root 'instances'),
    (Join-Path (Split-Path (Split-Path $Executable -Parent) -Parent) 'instances')) | Select-Object -Unique

function Read-BridgeReply($Reader) {
    $pending = $Reader.ReadLineAsync()
    if (-not $pending.Wait(2500)) { throw 'The editor did not answer in time.' }
    $reply = $pending.Result | ConvertFrom-Json
    return $reply
}

foreach ($owner in $owners) {
    foreach ($recordRoot in $recordRoots) {
        $recordFiles = @(Get-ChildItem -LiteralPath $recordRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Get-Item -LiteralPath (Join-Path $_.FullName 'editor.json') -ErrorAction SilentlyContinue })
        foreach ($recordFile in $recordFiles) {
            $pipe = $null
            $sent = $false
            try {
                $record = Get-Content -LiteralPath $recordFile.FullName -Raw | ConvertFrom-Json
                if ($record.pid -ne $owner.ProcessId -or $record.pipe -notmatch '^letitedit-[a-z0-9_-]+$') { continue }
                $pipe = [System.IO.Pipes.NamedPipeClientStream]::new('.', $record.pipe,
                    [System.IO.Pipes.PipeDirection]::InOut, [System.IO.Pipes.PipeOptions]::Asynchronous)
                $pipe.Connect(500)
                $encoding = [System.Text.UTF8Encoding]::new($false)
                $writer = [System.IO.StreamWriter]::new($pipe, $encoding, 1024, $true)
                $reader = [System.IO.StreamReader]::new($pipe, $encoding, $false, 1024, $true)
                $writer.AutoFlush = $true
                $writer.WriteLine('{"id":1,"method":"state","params":{}}')
                $state = Read-BridgeReply $reader
                if (-not $state.ok -or $state.result.instance.pid -ne $owner.ProcessId) { continue }
                $request = @{ id = 2; method = 'open'; params = @{ path = $Project } } | ConvertTo-Json -Compress
                $sent = $true
                $writer.WriteLine($request)
                $reply = Read-BridgeReply $reader
                if (-not $reply.ok) { $sent = $false; continue }
                Write-Output ('Opened in existing letitedit window: ' + $owner.ProcessId)
                exit 0
            } catch {
                if ($sent) {
                    Write-Warning 'The open request may already be in the editor. Not opening a duplicate window.'
                    exit 2
                }
            } finally {
                if ($null -ne $pipe) { $pipe.Dispose() }
            }
        }
    }
}

$hash = [System.Security.Cryptography.SHA256]::Create()
try {
    $identity = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant()))).Replace('-', '').Substring(0, 16).ToLowerInvariant()
} finally { $hash.Dispose() }
$env:LETITEDIT_INSTANCE = 'mlt-' + $identity
if ($owners.Count) { $env:LETITEDIT_INSTANCE += '-' + [guid]::NewGuid().ToString('N').Substring(0, 6) }
$env:LETITEDIT_OWNER = ''
$env:LETITEDIT_TOOL_SERVER_PID = ''
$start = [System.Diagnostics.ProcessStartInfo]::new()
$start.FileName = $Executable
$start.Arguments = '--noupgrade --appdata "' + $appdata + '" -- "' + $Project + '"'
$start.WorkingDirectory = Split-Path $Executable -Parent
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$child = [System.Diagnostics.Process]::Start($start)
Write-Output ('Started letitedit with normal appdata: ' + $child.Id)
$child.Dispose()
