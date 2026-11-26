# Offline OCR worker: Windows' own text recognizer (Windows.Media.Ocr, part of Windows 10/11, no download).
# Reads one image path per line on stdin and writes one JSON line per image on stdout:
#   {"path": ..., "w": W, "h": H, "lang": "en-US", "ms": N,
#    "lines": [{"text": ..., "words": [{"text": ..., "x": .., "y": .., "w": .., "h": ..}]}]}
# or {"path": ..., "error": "..."}. An empty line or "quit" ends the worker. Started by bridge/ocr.py.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File ocr_worker.ps1 [-Lang en-US]
param([string]$Lang = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    return $task.Result
}

if ($Lang) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))
} else {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    [Console]::Out.WriteLine((@{ error = 'no OCR language available (Windows Settings > Language: add an OCR-capable language)' } | ConvertTo-Json -Compress))
    exit 2
}
$tag = $engine.RecognizerLanguage.LanguageTag
[Console]::Out.WriteLine((@{ ready = $true; lang = $tag; max_dim = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension } | ConvertTo-Json -Compress))
[Console]::Out.Flush()

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $path = $line.Trim()
    if ($path -eq '' -or $path -eq 'quit') { break }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        try {
            $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $lines = @()
            foreach ($ln in $res.Lines) {
                $words = @()
                foreach ($wd in $ln.Words) {
                    $r = $wd.BoundingRect
                    $words += @{ text = $wd.Text; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height }
                }
                $lines += @{ text = $ln.Text; words = $words }
            }
            $out = @{ path = $path; w = [int]$bitmap.PixelWidth; h = [int]$bitmap.PixelHeight; lang = $tag;
                      ms = [int]$sw.ElapsedMilliseconds; lines = $lines }
            $bitmap.Dispose()
        } finally {
            $stream.Dispose()
        }
    } catch {
        $out = @{ path = $path; error = ($_.Exception.Message -replace '\s+', ' ') }
    }
    [Console]::Out.WriteLine(($out | ConvertTo-Json -Compress -Depth 6))
    [Console]::Out.Flush()
}
