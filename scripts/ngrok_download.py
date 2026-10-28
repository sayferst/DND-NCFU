"""Bounded official Windows download with native publisher verification."""

import http.client
import io
import os
import subprocess
import urllib.request
import zipfile

URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
MAX_ARCHIVE = 40 * 1024 * 1024
MAX_BINARY = 100 * 1024 * 1024
WINDOWS = os.name == "nt"


def windows_payload(path):
    """Use Windows system proxy/CA settings; enforce the same byte/TLS limits."""
    archive = path.with_suffix(".download.zip")
    environment = os.environ.copy()
    for name in ("NGROK_AUTHTOKEN", "NGROK_API_KEY", "PSModulePath"):
        environment.pop(name, None)
    environment["DND_NGROK_ZIP"] = str(archive.resolve())
    script = (
        "$ErrorActionPreference='Stop'; $response=$null; $inputStream=$null; $output=$null; "
        "try { "
        f"$request=[System.Net.WebRequest]::Create('{URL}'); "
        "$request.Timeout=120000; $request.ReadWriteTimeout=120000; "
        "$request.UserAgent='DND-NCFU-ngrok-updater/0.4'; "
        "$response=$request.GetResponse(); "
        "if ($response.ResponseUri.Scheme -ne 'https') {throw 'HTTPS required'}; "
        "$inputStream=$response.GetResponseStream(); "
        "$output=[System.IO.File]::Create($env:DND_NGROK_ZIP); "
        "$buffer=New-Object byte[] 65536; $total=0; "
        "while (($count=$inputStream.Read($buffer,0,$buffer.Length)) -gt 0) { "
        f"$total+=$count; if ($total -gt {MAX_ARCHIVE}) {{throw 'Archive too large'}}; "
        "$output.Write($buffer,0,$count) }; "
        "} finally { if ($output) {$output.Dispose()}; "
        "if ($inputStream) {$inputStream.Dispose()}; if ($response) {$response.Close()} }"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            timeout=240,
            check=False,
        )
        if result.returncode or not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE:
            raise ValueError("Windows HTTPS download failed")
        return archive.read_bytes()
    finally:
        archive.unlink(missing_ok=True)


def payload(path):
    try:
        with urllib.request.urlopen(URL, timeout=30) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("HTTPS required")
            result = bytearray()
            while chunk := response.read(min(65536, MAX_ARCHIVE + 1 - len(result))):
                result.extend(chunk)
                if len(result) > MAX_ARCHIVE:
                    raise ValueError("Archive too large")
            expected = getattr(response, "headers", {}).get("Content-Length", "")
            if expected.isdigit() and int(expected) != len(result):
                raise http.client.IncompleteRead(b"", int(expected))
            return bytes(result)
    except (OSError, http.client.HTTPException):
        if not WINDOWS:
            raise
        print("Повторяю полную загрузку через системный HTTPS Windows…", flush=True)
        return windows_payload(path)


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
        data = payload(path)
        if len(data) > MAX_ARCHIVE:
            raise ValueError("Archive too large")
        stage = "ZIP"
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [info for info in archive.infolist() if info.filename == "ngrok.exe"]
            if len(entries) != 1 or not 0 < entries[0].file_size <= MAX_BINARY:
                raise ValueError("Invalid binary entry")
            binary = archive.read(entries[0])
        if not binary.startswith(b"MZ"):
            raise ValueError("Not a Windows executable")
        path.write_bytes(binary)
        stage = "Authenticode"
        verify_publisher(path)
    except (OSError, ValueError, http.client.HTTPException, subprocess.SubprocessError):
        path.unlink(missing_ok=True)
        raise ValueError(
            f"Не удалось загрузить и проверить официальный ngrok ({stage}). "
            "Проверьте доступ к bin.equinox.io и проверку подписи Windows. "
            "Существующий агент и ключи сохранены."
        ) from None
