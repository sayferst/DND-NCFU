# Reproducible developer build. No model calls, user-data migration or credentials.
param(
    [switch]$Installer,
    [ValidateSet('developer', 'tester')][string]$Profile = 'developer',
    [string]$GatewayUrl = '',
    [string]$DiscoveryUrl = '',
    [string]$DiscoveryKey = '',
    [string]$BootstrapFile = '',
    [string]$TextModel = 'deepseek/deepseek-v4-flash-latest'
)
$ErrorActionPreference = 'Stop'
if ($Profile -eq 'tester' -and !$DiscoveryUrl -and !$GatewayUrl.StartsWith('https://')) {
    throw 'Tester Build: укажите реальный HTTPS-адрес игрового сервиса через -GatewayUrl. Ключ API не передавайте.'
}
if ($env:OS -ne 'Windows_NT' -or ![Environment]::Is64BitOperatingSystem) {
    throw 'Сборка требует Windows x64.'
}
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (!(Test-Path $python)) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Установите Python 3.12 x64 для сборки.' }
}
& $python -c "import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Нужно окружение .venv с Python 3.12 x64.' }
& $python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить проверенные зависимости сборки.' }
& $python scripts\repair_fixture_checkout.py
if ($LASTEXITCODE -ne 0) { throw 'Ошибка проверки исходных фикстур.' }
& $python scripts\check.py
if ($LASTEXITCODE -ne 0) { throw 'Проверки не прошли. Сборка остановлена.' }
$version = (& $python scripts\release_tools.py version).Trim()
$stamp = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,6)
$stage = Join-Path (Get-Location) ('build\windows-' + $stamp)
$checks = Join-Path $stage 'checks'
New-Item -ItemType Directory -Path $checks -Force | Out-Null
$oldDiscoveryUrl = $env:DND_DISCOVERY_URL
$oldDiscoveryKey = $env:DND_DISCOVERY_KEY
$oldBootstrapFile = $env:DND_BOOTSTRAP_FILE
$oldBuildProfile = $env:DND_BUILD_PROFILE
$oldGatewayUrl = $env:DND_GATEWAY_URL
$oldTextModel = $env:DND_TEXT_MODEL
try {
    $env:DND_DISCOVERY_URL = $DiscoveryUrl
    $env:DND_DISCOVERY_KEY = $DiscoveryKey
    $env:DND_BOOTSTRAP_FILE = $BootstrapFile
    $env:DND_BUILD_PROFILE = $Profile
    $env:DND_GATEWAY_URL = $GatewayUrl
    $env:DND_TEXT_MODEL = $TextModel
    & $python -m PyInstaller --clean --noconfirm --distpath (Join-Path $stage 'dist') --workpath (Join-Path $stage 'work') DND-NCFU.spec
} finally {
    $env:DND_DISCOVERY_URL = $oldDiscoveryUrl
    $env:DND_DISCOVERY_KEY = $oldDiscoveryKey
    $env:DND_BOOTSTRAP_FILE = $oldBootstrapFile
    $env:DND_BUILD_PROFILE = $oldBuildProfile
    $env:DND_GATEWAY_URL = $oldGatewayUrl
    $env:DND_TEXT_MODEL = $oldTextModel
}
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller не создал пакет.' }
$bundle = Join-Path $stage 'dist\DND-NCFU'
$exe = Join-Path $bundle 'DND-NCFU.exe'
& $python scripts\release_tools.py verify --folder $bundle | Out-File (Join-Path $checks 'bundle.json') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Состав Windows-пакета не прошёл проверку.' }
# Launch outside checkout, with no Python/venv on PATH. The smoke test uses temporary data.
$oldPath = $env:PATH
$oldData = $env:RPG_VKR_DATA_DIR
$oldPythonPath = $env:PYTHONPATH
$oldPythonHome = $env:PYTHONHOME
try {
    $env:PATH = "$env:SystemRoot\system32;$env:SystemRoot"
    $env:PYTHONPATH = ''
    $env:PYTHONHOME = ''
    $env:RPG_VKR_DATA_DIR = Join-Path $checks 'temporary-user-data'
    foreach ($mode in @('self-check','smoke-test')) {
        $report = Join-Path $checks ($mode + '.json')
        $process = Start-Process -FilePath $exe -WorkingDirectory $checks `
            -ArgumentList @("--$mode", '--report', ('"' + $report + '"')) -PassThru
        if (!$process.WaitForExit(180000)) {
            $process.Kill()
            throw "EXE не закончил $mode за 180 секунд."
        }
        $process.Refresh()
        if ($process.ExitCode -ne 0 -or !(Test-Path $report)) { throw "EXE не прошёл $mode." }
        $nativeReport = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($nativeReport.ok -ne $true) { throw "${mode}: неверный отчёт." }
    }
} finally {
    $env:PATH = $oldPath
    $env:RPG_VKR_DATA_DIR = $oldData
    $env:PYTHONPATH = $oldPythonPath
    $env:PYTHONHOME = $oldPythonHome
}
$archiveName = "DND-NCFU-Windows-x64-v$version.zip"
$archive = Join-Path $stage $archiveName
& $python scripts\release_tools.py archive --folder $bundle --output $archive --checks $checks
if ($LASTEXITCODE -ne 0) { throw 'Архив не прошёл проверку.' }
$dist = Join-Path (Get-Location) 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$previous = Join-Path $dist ('previous\' + $stamp)
foreach ($name in @('DND-NCFU', $archiveName, ($archiveName + '.sha256'))) {
    $old = Join-Path $dist $name
    if (Test-Path $old) {
        New-Item -ItemType Directory -Path $previous -Force | Out-Null
        Move-Item -LiteralPath $old -Destination $previous
    }
}
Move-Item -LiteralPath $bundle -Destination $dist
Move-Item -LiteralPath $archive -Destination $dist
Move-Item -LiteralPath ($archive + '.sha256') -Destination $dist
if ($Installer) {
    $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $iscc = if ($compiler) { $compiler.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
    if (!(Test-Path $iscc)) { throw 'Portable готова. Для установщика установите Inno Setup 6 и повторите с -Installer.' }
    & $iscc ("/DAppVersion=" + $version) ("/DBundleDir=" + (Join-Path $dist 'DND-NCFU')) ("/DReleaseDir=" + $dist) installer\DND-NCFU.iss
    if ($LASTEXITCODE -ne 0) { throw 'Portable готова, установщик не собран.' }
}
Write-Host "Готово: $(Join-Path $dist 'DND-NCFU\DND-NCFU.exe')"
Write-Host "ZIP: $(Join-Path $dist $archiveName)"
Write-Host 'Переносите всю папку. Пользовательские данные не изменялись.'
