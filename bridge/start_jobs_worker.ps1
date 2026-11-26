# Starts the letitedit background job worker (jobs.py) when it is not already running, so jobs interrupted by a
# restart or sign-out continue. Safe to run any number of times: a second worker exits at once.
# NOT registered anywhere. To run it at sign-in, a Task Scheduler entry (At log on, current user) would run:
#   powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File <letitedit folder>\bridge\start_jobs_worker.ps1
# Python: the install's own (<letitedit folder>\env\Scripts\python.exe); a copy without one (the development folder)
# uses the first python.exe on PATH.
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) { throw "No Python: $py is missing and there is no python.exe on PATH" }
    $py = $found.Source
}
$jobs = Join-Path $PSScriptRoot 'jobs.py'
& $py $jobs ensure-worker
