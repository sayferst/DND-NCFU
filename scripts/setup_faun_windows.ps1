param([switch]$CheckOnly, [string]$Report)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) { throw "Project Python .venv is missing. Run the project setup first." }
    $SetupArgs = @("-m", "training.setup_faun")
    if ($CheckOnly) { $SetupArgs += "--check-only" } else { $SetupArgs += "--interactive" }
    if ($Report) { $SetupArgs += @("--report", $Report) }
    & $PythonExe @SetupArgs
    if ($LASTEXITCODE -ne 0) { throw "Faun setup could not finish. See the diagnostic report." }
} finally { Pop-Location }
