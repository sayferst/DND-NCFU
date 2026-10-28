"""Bounded official Windows download with native publisher verification."""

import io
import os
import subprocess
import urllib.request
import zipfile

URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
MAX_ARCHIVE = 40 * 1024 * 1024
MAX_BINARY = 100 * 1024 * 1024


def verify_publisher(path):
    environment = os.environ.copy()
    for name in ("NGROK_AUTHTOKEN", "NGROK_API_KEY"):
        environment.pop(name, None)
    # A caller running pwsh can export PS7 module paths into Windows PowerShell5.
    environment.pop("PSModulePath", None)
    environment["DND_NGROK_VERIFY_PATH"] = str(path.resolve())
    script = (
        "$ErrorActionPreference='Stop'; "
        'Import-Module "$PSHOME\\Modules\\Microsoft.PowerShell.Security'
        '\\Microsoft.PowerShell.Security.psd1"; '
        "$s=Get-AuthenticodeSignature -LiteralPath $env:DND_NGROK_VERIFY_PATH; "
        "if ($s.Status -ne 'Valid' -or !$s.SignerCertificate) {exit 1}; "
        "$n=$s.SignerCertificate.GetNameInfo("
        "[System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false); "
        "if ($n -ne 'ngrok, Inc.') {exit 1}; exit 0"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise ValueError("Подпись официального ngrok не подтверждена. Установка остановлена.")


def download_agent(path):
    stage = "HTTPS"
    try:
        with urllib.request.urlopen(URL, timeout=30) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("HTTPS required")
            payload = response.read(MAX_ARCHIVE + 1)
        if len(payload) > MAX_ARCHIVE:
            raise ValueError("Archive too large")
        stage = "ZIP"
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = [info for info in archive.infolist() if info.filename == "ngrok.exe"]
            if len(entries) != 1 or not 0 < entries[0].file_size <= MAX_BINARY:
                raise ValueError("Invalid binary entry")
            binary = archive.read(entries[0])
        if not binary.startswith(b"MZ"):
            raise ValueError("Not a Windows executable")
        path.write_bytes(binary)
        stage = "Authenticode"
        verify_publisher(path)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError):
        path.unlink(missing_ok=True)
        raise ValueError(
            f"Не удалось загрузить и проверить официальный ngrok ({stage}). "
            "Проверьте доступ к bin.equinox.io и проверку подписи Windows. "
            "Существующий агент и ключи сохранены."
        ) from None
