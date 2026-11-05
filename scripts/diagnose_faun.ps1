param([string]$Output = "faun-hardware-report.json")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) { throw "Project Python .venv is missing." }
    & $PythonExe -m training.hardware_preflight --scope owner_laptop --output $Output
    if ($LASTEXITCODE -ne 0) { throw "Hardware report failed." }
    Write-Host "Report saved. No model, driver or paid resource was installed."
} finally {
    Pop-Location
}
