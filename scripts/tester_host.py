"""Owner-only Windows host: signed Quick Tunnel discovery and personalized Setup."""

import argparse
import base64
import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from rpg_vkr.discovery import (  # noqa: E402
    canonical,
    discovery_url,
    fetch,
    public_endpoint,
)
from rpg_vkr.storage.connection import load_secret, save_secret  # noqa: E402
from scripts.tunnel_supervision import (  # noqa: E402
    PublicMonitor,
    RestartBudget,
    RestartTunnel,
    write_ready,
)
from server.gateway import (  # noqa: E402
    FLUX,
    RECRAFT,
    Denied,
    Gateway,
    Server,
    Store,
    Upstream,
)

BRANCH = "tester-host-address"
DISCOVERY = "https://raw.githubusercontent.com/sayferst/DND-NCFU/" + BRANCH + "/endpoint.json"


def cloudflared_path():
    found = shutil.which("cloudflared")
    if found:
        return found
    # MSI installation may be missing from the current terminal's inherited PATH.
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            for relative in (
                "cloudflared/cloudflared.exe",
                "Cloudflare/cloudflared.exe",
                "Microsoft/WinGet/Links/cloudflared.exe",
            ):
                path = Path(root) / relative
                if path.is_file():
                    return str(path)
    raise ValueError(
        "cloudflared не найден. Откройте PowerShell заново и выполните проверку инструментов."
    )


def tunnel_command(executable, port, edges=(), *, protocol="http2"):
    if protocol not in {"http2", "quic"}:
        raise ValueError("Неподдерживаемый транспорт Cloudflare.")
    # HTTP/2 uses TCP7844 rather than QUIC/UDP7844. No Windows firewall changes.
    command = [
        executable,
        "tunnel",
        "--protocol",
        protocol,
        "--url",
        f"http://127.0.0.1:{port}",
        "--no-autoupdate",
    ]

    for edge in edges:
        # Numeric endpoints only: never pass a hostname/option from DNS into argv.
        import ipaddress

        address, separator, port_text = edge.rpartition(":")
        if not separator or port_text != "7844":
            raise ValueError("Invalid tunnel edge")
        parsed = ipaddress.ip_address(address)
        if parsed.version != 4 or not parsed.is_global:
            raise ValueError("Invalid tunnel edge")
        command.extend(["--edge", str(parsed) + ":7844"])
    return command


def read_tunnel_output(stream, urls, connections):
    reported = set()
    try:
        for line in stream:
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if match:
                urls.put(match.group())
            if "Registered tunnel connection" in line:
                connections.put(True)
            lowered = line.lower()
            categories = (
                ("failed to dial", "Cloudflare: не удалось установить исходящее соединение."),
                ("timeout", "Cloudflare: истекло время ожидания исходящего соединения."),
                ("no such host", "Cloudflare: ошибка DNS при поиске узла туннеля."),
                ("x509:", "Cloudflare: ошибка проверки TLS-сертификата."),
                ("unable to reach the origin", "Cloudflare: локальный шлюз недоступен туннелю."),
                ("connection terminated", "Cloudflare: соединение коннектора завершено."),
                ("connection reset", "Cloudflare: сетевое соединение сброшено."),
                ("failed to serve tunnel", "Cloudflare: обслуживание соединения туннеля прервано."),
            )
            for marker, message in categories:
                if marker in lowered and marker not in reported:
                    print(message, flush=True)
                    reported.add(marker)
    finally:
        urls.put(None)
        connections.put(False)


def wait_for_tunnel_connection(connections, *, protocol="http2"):
    try:
        connected = connections.get(timeout=90)
    except queue.Empty:
        transport = "TCP7844" if protocol == "http2" else "UDP7844"
        raise ValueError(
            "cloudflared не подтвердил соединение за90с. "
            "Проверьте доступ cloudflared.exe к исходящему " + transport + " в вашей сети. "
            "Входящий порт открывать не требуется."
        ) from None
    if not connected:
        raise ValueError("cloudflared завершился до подключения к Cloudflare.")


def inno_compiler():
    """Find machine-wide, per-user and PATH installations without a broad disk scan."""
    found = shutil.which("ISCC.exe")
    candidates = [Path(found)] if found else []
    roots = (
        (os.environ.get("ProgramFiles(x86)"), "Inno Setup 6/ISCC.exe"),
        (os.environ.get("ProgramFiles"), "Inno Setup 6/ISCC.exe"),
        (os.environ.get("LOCALAPPDATA"), "Programs/Inno Setup 6/ISCC.exe"),
    )
    candidates.extend(Path(root) / relative for root, relative in roots if root)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return ""


def host_process_alive(pid):
    if type(pid) is not int or pid < 1:
        return False
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def build_preflight(root):
    path = root / "host-ready.json"
    if not path.is_file():
        raise ValueError("Хост не запущен или не готов. Выполните start в отдельном окне.")
    try:
        if path.stat().st_size > 8192:
            raise ValueError
        ready = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(ready, dict) or not all(
            key in ready for key in ("pid", "discovery", "verification_key", "sequence")
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError("Повреждён host-ready.json. Перезапустите start.") from None
    if not host_process_alive(ready["pid"]):
        raise ValueError("Хост завершился. Запустите start и оставьте окно открытым.")
    try:
        discovery_url(ready["discovery"])
        verified = fetch(ready["discovery"], ready["verification_key"], previous=ready["sequence"])
    except (ValueError, OSError, TypeError, KeyError) as error:
        raise ValueError(
            "Проверка подписанного адреса GitHub: " + public_check_reason(error)
        ) from None
    try:
        check_health(verified["endpoint"])
    except (ValueError, OSError, TypeError, KeyError) as error:
        raise ValueError(
            "Сборка остановлена: публичный HTTPS-шлюз недоступен: "
            + public_check_reason(error)
            + ". Допуск не создавался. Оставьте start открытым и восстановите соединение."
        ) from None
    return ready


BUILD_STAGES = {
    "dependencies": "установка зависимостей",
    "checks": "проверки проекта",
    "pyinstaller": "создание EXE (PyInstaller)",
    "bundle": "проверка содержимого EXE",
    "self-check": "самопроверка EXE",
    "smoke-test": "проверка запуска EXE",
    "archive": "создание архива",
    "inno": "компилятор Inno Setup",
    "complete": "передача результата сборки",
}


def build_failure(report, code):
    stage = "сборщик Windows"
    try:
        if report.stat().st_size <= 4096:
            value = json.loads(report.read_text(encoding="utf-8-sig"))
            if isinstance(value, dict) and isinstance(value.get("stage"), str):
                stage = BUILD_STAGES.get(value["stage"], stage)
    except (OSError, ValueError, TypeError, RecursionError):
        pass
    return ValueError(f"Сборка не завершена: {stage}, код {int(code)}. Подробности выше в консоли.")


def signed_manifest(private, endpoint, sequence, now=None):
    now = int(time.time() if now is None else now)
    value = {
        "version": 1,
        "sequence": sequence,
        "issued": now,
        "expires": now + 32 * 86400,
        "endpoint": public_endpoint(endpoint),
    }
    value["signature"] = base64.b64encode(private.sign(canonical(value))).decode()
    return value


def git(*args, cwd=ROOT, capture=True):
    return subprocess.check_output(
        ["git", *args], cwd=cwd, text=True, stderr=subprocess.PIPE if capture else None
    ).strip()


def publish(manifest):
    # A separate branch contains ONLY the signed public document. Never stage the checkout
    # or any owner state, bootstrap code, API key, private signing key or grant database.
    remote = git("remote", "get-url", "origin")
    if remote not in (
        "https://github.com/sayferst/DND-NCFU.git",
        "git@github.com:sayferst/DND-NCFU.git",
    ):
        raise ValueError("Для публикации нужен существующий origin sayferst/DND-NCFU.")
    with tempfile.TemporaryDirectory(prefix="dnd-public-address-") as folder:
        git("init", "--quiet", cwd=folder)
        git("remote", "add", "origin", remote, cwd=folder)
        existing = git("ls-remote", "--heads", "origin", "refs/heads/" + BRANCH, cwd=folder)
        if existing:
            git("fetch", "--quiet", "--depth=1", "origin", BRANCH, cwd=folder)
            git("checkout", "--quiet", "-b", BRANCH, "FETCH_HEAD", cwd=folder)
        else:
            git("checkout", "--quiet", "--orphan", BRANCH, cwd=folder)
        git("config", "user.name", "DND tester host", cwd=folder)
        git("config", "user.email", "tester-host@users.noreply.github.com", cwd=folder)
        (Path(folder) / "endpoint.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        git("add", "--", "endpoint.json", cwd=folder)
        git("commit", "--quiet", "-m", "Update signed tester gateway address", cwd=folder)
        git("push", "--quiet", "origin", "HEAD:refs/heads/" + BRANCH, cwd=folder)


@contextmanager
def host_lock(root):
    import msvcrt

    with (root / "host.lock").open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("Хост уже запущен в другом окне.") from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def check_health(endpoint):
    from scripts.tunnel_health import probe

    probe(endpoint)


def public_check_reason(error):
    """Only controlled categories: never echo exception URLs or response bodies."""
    if isinstance(error, urllib.error.HTTPError):
        from scripts.tunnel_health import CF_ERRORS

        code = getattr(error, "gateway_details", {}).get("cloudflare_code", "")
        detail = f", Cloudflare {code}: {CF_ERRORS[code]}" if code in CF_ERRORS else ""
        return f"HTTP {error.code}" + detail
    if isinstance(error, (TimeoutError, urllib.error.URLError, OSError)):
        return "сетевая ошибка, DNS, TLS или тайм-аут"
    return "подпись, версия, адрес или формат ответа не прошли проверку"


def diagnose_tunnel(root):
    """Read a verified public endpoint and compare OS proxy versus direct HTTPS GETs."""
    from scripts.tunnel_health import result

    report = {
        "check": "signed tunnel health and proxy routes",
        "paid_requests": 0,
        "grant_created": False,
        "secrets_read": False,
        "system_settings_changed": False,
        "proxy_configured": any(k in urllib.request.getproxies() for k in ("http", "https", "all")),
    }
    try:
        path = root / "host-ready.json"
        if path.stat().st_size > 8192:
            raise ValueError
        ready = json.loads(path.read_text(encoding="utf-8"))
        verified = fetch(ready["discovery"], ready["verification_key"], previous=ready["sequence"])
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        report.update(ok=False, discovery_ok=False, reason=public_check_reason(error))
        return report
    report.update(discovery_ok=True, host_process_alive=host_process_alive(ready.get("pid")))
    samples = []
    for index in range(3):
        for direct in (False, True):
            samples.append(
                {
                    "route": "direct" if direct else "system",
                    **result(verified["endpoint"], direct=direct),
                }
            )
        if index < 2:
            time.sleep(2)
    system_ok = all(s["ok"] for s in samples if s["route"] == "system")
    direct_ok = all(s["ok"] for s in samples if s["route"] == "direct")
    codes = {s.get("cloudflare_code") for s in samples}
    diagnosis = (
        "system_proxy_route"
        if direct_ok and not system_ok and report["proxy_configured"]
        else "route_difference"
        if direct_ok and not system_ok
        else "connector_lost_1033"
        if "1033" in codes
        else "origin_dns_1016"
        if "1016" in codes
        else "ready"
        if system_ok and report["host_process_alive"]
        else "unstable_or_unreachable"
    )
    report.update(
        ok=system_ok and report["host_process_alive"], samples=samples, diagnosis=diagnosis
    )
    return report


def wait_for_public_host(endpoint, public_key, sequence, *, timeout=300, samples=3, process=None):
    from rpg_vkr.gateway_http import is_ngrok

    deadline = time.monotonic() + timeout
    next_update = 0
    last_status = None
    successes = 0
    while True:
        if process is not None and process.poll() is not None:
            raise RestartTunnel("Коннектор завершился до подтверждения устойчивого HTTPS.")
        phase = "подписанный документ GitHub"
        try:
            verified = fetch(DISCOVERY, public_key, previous=sequence)
            if verified["endpoint"] != public_endpoint(endpoint):
                raise ValueError("Адрес ещё не обновился.")
            phase = (
                "HTTPS-туннель "
                + ("ngrok" if is_ngrok(endpoint) else "Cloudflare")
                + " (/api/v1/health)"
            )
            check_health(verified["endpoint"])
            successes += 1
            if successes >= samples:
                return verified
            if time.monotonic() >= deadline:
                raise RestartTunnel("Не подтверждена устойчивость HTTPS-туннеля.")
            time.sleep(5)
        except (ValueError, OSError) as error:
            successes = 0
            reason = public_check_reason(error)
            now = time.monotonic()
            if now >= deadline:
                raise ValueError(
                    "Не удалось подтвердить готовность: "
                    + phase
                    + ": "
                    + reason
                    + ". Платная генерация не запускалась. "
                    "Повторите start; если ошибка сохраняется, передайте эту строку."
                ) from None
            if now >= next_update or last_status != (phase, reason):
                print(
                    "Ожидаю доступность: "
                    + phase
                    + ": "
                    + reason
                    + ". Повторяю только проверку доступности (до 5 минут)…",
                    flush=True,
                )
                next_update = now + 15
                last_status = (phase, reason)
            time.sleep(min(3, max(0, deadline - now)))


def private_key(root):
    path = root / "signing-key.bin"
    encoded = load_secret(path)
    if not encoded:
        if path.exists():
            raise ValueError("Не удалось открыть ключ подписи. Не создавайте другой поверх него.")
        private = Ed25519PrivateKey.generate()
        encoded = base64.b64encode(private.private_bytes_raw()).decode()
        save_secret(path, encoded)
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded, validate=True))


PROVIDER_REASONS = {
    "master_key_not_supported": "В ответе RouterAI упомянуто ограничение для мастер-ключа. "
    "Выполните tester_host.cmd key и введите обычный ключ для запросов к моделям.",
    "master_key_required": "Для этой операции RouterAI запросил мастер-ключ. "
    "Шлюз не подменяет обычный ключ административным; требуется сверить API-контракт.",
    "authorization_format": "RouterAI сообщил о неверном формате авторизации. "
    "При замене ключа вводите только сам обычный API-ключ, без Bearer, кавычек или JSON.",
    "authorization_missing": "RouterAI сообщил об отсутствии данных авторизации. "
    "Шлюз передаёт Bearer; требуется проверить ключ и сетевой путь.",
    "key_rejected": "Ответ RouterAI указывает на отклонённый формат или значение API-ключа. "
    "Проверьте, что это обычный ключ именно RouterAI.",
    "key_inactive": "Ответ RouterAI указывает на выключенный, отозванный или истёкший ключ.",
    "body_rejected": "Ответ RouterAI указывает на отклонённое тело или JSON запроса метаданных.",
    "operation_unavailable": "Ответ RouterAI указывает на неподдерживаемую операцию метаданных.",
    "quota_rejected": "Ответ RouterAI указывает на ограничение квоты или баланса.",
    "access_denied": "Ответ RouterAI указывает на запрет доступа к операции метаданных.",
}


def metadata_failure(error, label):
    messages = {
        "upstream_http_400": (
            "RouterAI отклонил запрос метаданных (HTTP400). "
            "Передайте этот текст владельцу проекта; ключ не присылайте."
        ),
        "upstream_http_401": (
            "Ключ RouterAI отклонён (HTTP401). Проверьте его командой tester_host.cmd key."
        ),
        "upstream_http_403": (
            "RouterAI запретил доступ (HTTP403). Проверьте права ключа и доступ из вашей сети."
        ),
        "upstream_http_402": (
            "RouterAI сообщил об ограничении оплаты (HTTP402). Проверьте баланс в кабинете."
        ),
        "upstream_http_429": (
            "RouterAI ограничил частоту запросов (HTTP429). Повторите запуск позже."
        ),
        "upstream_tls": (
            "Не удалось проверить TLS-сертификат RouterAI. Проверьте дату "
            "Windows и HTTPS-соединение."
        ),
        "upstream_timeout": (
            "Истекло время ожидания RouterAI. Проверьте интернет и повторите запуск."
        ),
        "upstream_network": (
            "Не удалось соединиться с RouterAI. Проверьте интернет и доступ к routerai.ru."
        ),
        "upstream_invalid_json": "RouterAI вернул неподдержанный формат метаданных.",
        "upstream_response_size": "Ответ метаданных RouterAI превысил допустимый размер.",
    }
    reason = PROVIDER_REASONS.get(getattr(error, "provider_reason", ""))
    if reason:
        return ValueError(label + ": " + reason + " Платная генерация не запускалась.")
    reason = messages.get(error.code)
    if reason is None:
        match = re.fullmatch(r"upstream_http_([1-5][0-9]{2})", error.code)
        reason = (
            f"RouterAI вернул HTTP {match[1]} при проверке метаданных. Повторите запуск позже."
            if match
            else "RouterAI временно не подтвердил метаданные. Повторите запуск позже."
        )
    return ValueError(label + ": " + reason + " Платная генерация не запускалась.")


def diagnose_provider(upstream):
    from rpg_vkr.narrative.routerai import parse_allowance

    report = {
        "check": "RouterAI metadata only",
        "operation": "GET /api/v1/key",
        "paid_requests": 0,
        "tunnel_started": False,
        "address_published": False,
        "secret_values_printed": False,
    }
    try:
        value = upstream.request("key")
    except Denied as error:
        match = re.fullmatch(r"upstream_http_([1-5][0-9]{2})", error.code)
        report.update(
            ok=False,
            http_status=int(match[1]) if match else None,
            provider_reason=(
                error.provider_reason
                if error.provider_reason in PROVIDER_REASONS
                else "unrecognized"
            ),
            reason_is_inferred=error.provider_reason in PROVIDER_REASONS,
            response_format=(
                error.response_format
                if error.response_format in {"json", "html", "text"}
                else "unavailable"
            ),
            message=str(metadata_failure(error, "Проверка ключа")),
        )
        return report
    try:
        parse_allowance(value)
        report.update(
            ok=True,
            http_status=200,
            provider_reason="allowance_confirmed",
            message="Метаданные ключа и положительный лимит подтверждены.",
        )
    except (ValueError, TypeError, ArithmeticError) as error:
        report.update(
            ok=False,
            http_status=200,
            provider_reason="allowance_not_confirmed",
            message=str(error) if isinstance(error, ValueError) else "Неверный формат лимита.",
        )
    return report


def check_provider(gateway):
    # Metadata GETs only: catch bad key, missing approved models and unknown prices
    # before reporting host readiness. Does not generate or consume a tester grant.
    from rpg_vkr.narrative.routerai import parse_allowance

    try:
        metadata = gateway.upstream.request("key")
    except Denied as error:
        raise metadata_failure(error, "Проверка ключа") from None
    try:
        parse_allowance(metadata)
    except (ValueError, TypeError, ArithmeticError) as error:
        # parse_allowance only emits controlled validation messages, never provider values.
        reason = str(error) if isinstance(error, ValueError) else "Неверный формат лимита ключа."
        raise ValueError(
            "Проверка ключа RouterAI: " + reason + " Платная генерация не запускалась."
        ) from None
    try:
        catalog = gateway.catalog()
    except Denied as error:
        raise metadata_failure(error, "Проверка каталога") from None
    available = {row["id"] for row in catalog["data"]}
    missing = sorted({gateway.text_model, RECRAFT, FLUX} - available)
    if missing:
        raise ValueError(
            "Каталог RouterAI: отсутствуют модели: "
            + ", ".join(missing)
            + ". Платная генерация не запускалась."
        )
    try:
        gateway.validate(
            "chat/completions",
            {
                "model": gateway.text_model,
                "messages": [{"role": "user", "content": "metadata price check"}],
                "max_tokens": 65536,
                "stream": False,
            },
            "world_seed",
        )
        for model in (RECRAFT, FLUX):
            gateway.validate(
                "images",
                {"model": model, "prompt": "metadata price check", "resolution": "1K", "n": 1},
                "image",
            )
    except Denied as error:
        raise metadata_failure(error, "Проверка каталога") from None
    except (ValueError, TypeError, KeyError, ArithmeticError):
        raise ValueError(
            "Каталог RouterAI не подтвердил утверждённые модели или цены. "
            "Платная генерация не запускалась; передайте владельцу проекта эту ошибку."
        ) from None


def host(root, store):
    (root / "host-ready.json").unlink(missing_ok=True)
    from scripts import ngrok_host

    settings = ngrok_host.load_settings(root)
    tunnel = ngrok_host.executable() if settings else cloudflared_path()
    ngrok_token = None
    if settings:
        ngrok_token = ngrok_host.validate_token(load_secret(root / "ngrok-token.bin"))
    private = private_key(root)
    key = load_secret(root / "routerai-key.bin")
    if key:
        print("Используется сохранённый ключ RouterAI. Замена: tester_host.cmd key.", flush=True)
    if not key:
        key = input("Введите RouterAI API-ключ (ввод виден): ").strip()
        Upstream(key)  # Validate before protecting; no request is made.
        save_secret(root / "routerai-key.bin", key)
    gateway = Gateway(store, Upstream(key))
    if (root / "account-mode.json").exists():
        gateway.account_upstreams = {}
        for account in ("admin", "tester"):
            credential = load_secret(root / ("account-" + account + "-key.bin"))
            gateway.account_upstreams["account_" + account] = Upstream(credential)
    print("Проверяю ключ и каталог RouterAI без генерации…", flush=True)
    check_provider(gateway)
    for upstream in getattr(gateway, "account_upstreams", {}).values():
        check_provider(Gateway(store, upstream))
    from scripts.tunnel_dns import reachable_edges, resolve_tunnel_edges

    server = Server(("127.0.0.1", 0), gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    budget = RestartBudget()
    attempt = 0
    try:
        while True:
            protocol = "http2" if attempt % 2 == 0 else "quic"
            try:
                if settings:
                    print("Запускаю ngrok через HTTPS/443…", flush=True)
                    with ngrok_host.running(
                        root, tunnel, server.server_port, settings["domain"], ngrok_token
                    ) as (process, endpoint):
                        serve_public_endpoint(root, private, endpoint, process)
                else:
                    print(
                        "Получаю узлы Cloudflare через DNS-over-HTTPS (без изменения Windows)…",
                        flush=True,
                    )
                    edges = resolve_tunnel_edges()
                    if protocol == "http2":
                        print("Проверяю исходящий TCP-доступ к узлам Cloudflare…", flush=True)
                        edges = reachable_edges(edges)
                    print("Транспорт Cloudflare: " + protocol, flush=True)
                    run_tunnel_session(root, server, private, tunnel, edges, protocol)
            except RestartTunnel as error:
                delay = budget.delay(time.monotonic())
                print(
                    str(error) + f". Пересоздаю коннектор через {delay}с; "
                    "шлюз, допуски и расходы сохраняются.",
                    flush=True,
                )
                attempt += 1
                time.sleep(delay)
    finally:
        (root / "host-ready.json").unlink(missing_ok=True)
        server.shutdown()
        server.server_close()


def run_tunnel_session(root, server, private, tunnel, edges, protocol):
    process = None
    reader = None
    try:
        process = subprocess.Popen(
            tunnel_command(tunnel, server.server_port, edges, protocol=protocol),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        urls = queue.Queue()

        connections = queue.Queue()
        reader = threading.Thread(
            target=read_tunnel_output, args=(process.stdout, urls, connections), daemon=True
        )
        reader.start()
        print("Шлюз запущен только на этом ПК. Ожидание HTTPS-туннеля…", flush=True)
        try:
            endpoint = urls.get(timeout=90)
        except queue.Empty:
            raise RestartTunnel("Туннель не выдал адрес за 90 секунд.") from None
        if not endpoint:
            raise RestartTunnel("cloudflared завершился до выдачи адреса.")
        print("Адрес получен. Ожидаю регистрацию соединения Cloudflare…", flush=True)
        try:
            wait_for_tunnel_connection(connections, protocol=protocol)
        except ValueError as error:
            raise RestartTunnel(str(error)) from None
        serve_public_endpoint(root, private, endpoint, process)
    finally:
        (root / "host-ready.json").unlink(missing_ok=True)
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if reader:
                reader.join(timeout=2)
            if process.stdout:
                process.stdout.close()


def serve_public_endpoint(root, private, endpoint, process):
    from rpg_vkr.gateway_http import health_interval

    interval = health_interval(endpoint)
    try:
        sequence_path = root / "sequence.txt"
        previous = int(sequence_path.read_text()) if sequence_path.exists() else 0
        sequence = max(previous + 1, time.time_ns() // 1000000)
        # Persist BEFORE publish; restart cannot roll back a previously used sequence.
        sequence_path.write_text(str(sequence), encoding="utf-8")
        manifest = signed_manifest(private, endpoint, sequence)
        print("Публикую подписанный адрес в отдельной ветке существующего GitHub…", flush=True)
        publish(manifest)
        # HTTP GET key is local-only/authenticated and never calls the paid upstream.
        public_key = base64.b64encode(private.public_key().public_bytes_raw()).decode()
        try:
            wait_for_public_host(endpoint, public_key, sequence, process=process)
        except ValueError as error:
            raise RestartTunnel(str(error)) from None
        ready = {
            "pid": os.getpid(),
            "discovery": DISCOVERY,
            "verification_key": public_key,
            "sequence": sequence,
        }
        write_ready(root, ready)
        print(
            "Адрес опубликован и подпись проверена. Платных проверок не было.\n"
            "Оставьте это окно открытым. Во втором окне: scripts\\tester_host.cmd build tester1\n"
            "Остановка: Ctrl+C. После перезапуска адрес обновится без нового Setup.",
            flush=True,
        )
        print(
            "Устойчивость подтверждена тремя HTTPS-проверками. Контроль продолжается.", flush=True
        )
        monitor = PublicMonitor(root, ready)
        next_probe = time.monotonic() + interval
        last_health = ""
        refresh_at = time.monotonic() + 7 * 86400
        while process.poll() is None:
            time.sleep(1)
            if time.monotonic() >= next_probe:
                health = monitor.check(
                    lambda: check_health(public_endpoint(endpoint)), public_check_reason
                )
                if health != last_health:
                    print(
                        "Туннель временно не готов: " + health
                        if health
                        else "Публичный HTTPS снова устойчив. Сборка разрешена.",
                        flush=True,
                    )
                    last_health = health
                next_probe = time.monotonic() + interval
            if time.monotonic() >= refresh_at:
                sequence += 1
                sequence_path.write_text(str(sequence), encoding="utf-8")
                publish(signed_manifest(private, endpoint, sequence))
                ready["sequence"] = sequence
                refresh_at = time.monotonic() + 7 * 86400
        raise RestartTunnel(f"Коннектор завершился, код {int(process.returncode)}")
    finally:
        (root / "host-ready.json").unlink(missing_ok=True)


def build(root, store, identity):
    if (root / "account-mode.json").exists():
        return build_accounts(root)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", identity):
        raise ValueError("Имя допуска: латинские буквы, цифры, _ или -; до60знаков.")
    # Fail before issuing a grant if Inno Setup is missing; no hidden installation.
    compiler = inno_compiler()
    if not compiler:
        raise ValueError(
            "Нужен Inno Setup6. Команда установки приведена в docs/TESTER_WITHOUT_DOMAIN.md."
        )
    ready = build_preflight(root)
    path = root / ("activation-" + identity + ".bin")
    code = load_secret(path)
    if not code:
        if path.exists():
            raise ValueError("Код допуска не расшифрован. Не заменяйте его новым.")
        code = store.bootstrap(identity, days=30, budget=100_000_000, requests=10000, worlds=100)
        save_secret(path, code)
    else:
        # A revoked/expired grant must never be repackaged as active.
        rows = {r["id"]: r for r in store.summary()}
        row = rows.get(identity)
        if not row or row["revoked"] or row["expires"] <= time.time():
            raise ValueError("Допуск отозван или истёк. Создайте нового тестировщика.")
    temporary = None
    report = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=root, delete=False, encoding="utf-8"
        ) as file:
            temporary = Path(file.name)
            json.dump({"code": code}, file)
        with tempfile.NamedTemporaryFile(dir=root, suffix=".json", delete=False) as file:
            report = Path(file.name)
        setup = ROOT / "dist" / "DND-NCFU-Setup.exe"
        before = (setup.stat().st_mtime_ns, setup.stat().st_size) if setup.is_file() else None
        command = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/build_windows.ps1"),
            "-Installer",
            "-Profile",
            "tester",
            "-DiscoveryUrl",
            ready["discovery"],
            "-DiscoveryKey",
            ready["verification_key"],
            "-BootstrapFile",
            str(temporary),
            "-InnoCompiler",
            compiler,
            "-BuildStatusFile",
            str(report),
        ]
        try:
            subprocess.run(command, cwd=ROOT, check=True)
        except subprocess.CalledProcessError as error:
            raise build_failure(report, error.returncode) from None
        except OSError:
            raise ValueError("Не удалось запустить PowerShell-сборщик Windows.") from None
        if not setup.is_file() or (setup.stat().st_mtime_ns, setup.stat().st_size) == before:
            raise ValueError(
                "Сборщик не создал новый DND-NCFU-Setup.exe. Старый Setup не передаётся."
            )
        destination = ROOT / "dist" / ("Tester-" + identity)
        destination.mkdir(exist_ok=True)
        shutil.copy2(setup, destination / setup.name)
        print("Персональный Setup: " + str(destination / setup.name))
        print("Передавайте только этому человеку. Допуск:100₽/30дней с момента создания.")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
        if report:
            report.unlink(missing_ok=True)


def build_accounts(root, *, installer=True):
    compiler = inno_compiler()
    if installer and not compiler:
        raise ValueError("Нужен Inno Setup 6.")
    ready = build_preflight(root)
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts/build_windows.ps1"),
        "-AccountLogin",
        "-Profile",
        "tester",
        "-DiscoveryUrl",
        ready["discovery"],
        "-DiscoveryKey",
        ready["verification_key"],
    ]
    if installer:
        command += ["-Installer", "-InnoCompiler", compiler]
    subprocess.run(command, cwd=ROOT, check=True)
    portable = ROOT / "dist" / ("Accounts-" + str(time.time_ns()))
    shutil.move(str(ROOT / "dist" / "DND-NCFU"), str(portable))
    print("EXE с входом по учётной записи: " + str(portable / "DND-NCFU.exe"))
    if not installer:
        return
    destination = ROOT / "dist" / "Release"
    destination.mkdir(exist_ok=True)
    (ROOT / "dist" / "DND-NCFU-Setup.exe").replace(destination / "setup.exe")
    print("Setup с входом admin/tester: " + str(destination))


def build_owner():
    from rpg_vkr.owner_local import admin_key

    Upstream(admin_key())  # Local DPAPI read and format validation only, no network.
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts/build_windows.ps1"),
        "-Profile",
        "owner",
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    destination = ROOT / "dist" / ("Owner-" + str(time.time_ns()))
    shutil.move(str(ROOT / "dist" / "DND-NCFU"), str(destination))
    print("Личный EXE без хоста: " + str(destination / "DND-NCFU.exe"))


def setup_accounts(root, store):
    import getpass

    from server.accounts import configure

    # Both roles are configured locally. No key or password is an argument or build input.
    for name in ("admin", "tester"):
        password = getpass.getpass("Пароль учётной записи " + name + ": ")
        confirmation = getpass.getpass("Повторите пароль: ")
        if password != confirmation:
            raise ValueError("Пароли не совпадают.")
        key = load_secret(root / ("account-" + name + "-key.bin"))
        if not key:
            raise ValueError("Сначала сохраните ключ через CHANGE_" + name.upper() + "_API.bat.")
        Upstream(key)
        save_secret(root / ("account-" + name + "-key.bin"), key)
        if name == "admin":
            save_secret(root / "routerai-key.bin", key)
        configure(store, name, password)
    (root / "account-mode.json").write_text('{"enabled":true}', encoding="utf-8")
    print("Учётные записи настроены: admin 500 ₽, tester 100 ₽; срок 30 дней.")
    print("Повторная настройка не сбрасывает расходы/срок. Перезапустите хост.")


def clipboard_key_text():
    # Fixed PowerShell code: clipboard text is DATA, never a command or process argument.
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$ErrorActionPreference = 'Stop'; $dndClipboard = Get-Clipboard -Raw; "
        "if ($null -eq $dndClipboard -or $dndClipboard.Length -gt 8192) { exit 2 }; "
        "[Console]::Out.Write($dndClipboard)"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-STA",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
        if len(result.stdout) > 32768:
            raise ValueError
        return result.stdout.decode("utf-8-sig")
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError(
            "Буфер обмена недоступен или слишком большой. "
            "Скопируйте только новый API-ключ и повторите key --clipboard."
        ) from None


def replace_owner_key(root, *, from_clipboard=False, account=None):
    from rpg_vkr.narrative.cloud import validate_api_key

    if from_clipboard:
        input(
            "Скопируйте новый API-ключ из кабинета RouterAI, затем нажмите Enter. "
            "Вставлять его в это окно не нужно: "
        )
        value = clipboard_key_text()
    else:
        value = input("Новый RouterAI API-ключ (ввод виден): ")
    # Browser copy controls can place a BOM/zero-width separator at the boundaries.
    # Internal characters are never removed or joined, so two pasted keys cannot merge.
    value = value.strip().strip("\ufeff\u200b").strip()
    try:
        validate_api_key(value)
    except ValueError:
        raise ValueError(
            "Ключ не сохранён: ввод пустой или содержит лишние символы. "
            "Используйте tester_host.cmd key --clipboard и скопируйте только сам ключ, "
            "без слов API, Bearer, кавычек или JSON."
        ) from None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        raise ValueError(
            "Ключ не сохранён: скопируйте его без кавычек и повторите key --clipboard."
        )
    if account not in {None, "admin", "tester"}:
        raise ValueError("Выберите admin или tester.")
    if account:
        save_secret(root / ("account-" + account + "-key.bin"), value)
    if account != "tester":
        save_secret(root / "routerai-key.bin", value)
    print(
        "Новый ключ сохранён для Мастера и Художника"
        + (" учётной записи " + account if account else "")
        + ". Перезапустите хост для применения."
    )


class AccountStore(Store):
    """Account-mode hosts cannot keep authorizing old bootstrap installations."""

    def identity(self, token):
        user = super().identity(token)
        if user["id"] not in {"account_admin", "account_tester"}:
            raise Denied(401, "account_login_required")
        return user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start")
    commands.add_parser("accounts", help="Настроить пароли и отдельные ключи admin/tester")
    commands.add_parser("build-exe", help="Собрать личный admin EXE без хоста и входа")
    commands.add_parser("update-ngrok", help="Обновить отдельную копию агента ngrok")
    ngrok_command = commands.add_parser("ngrok", help="Настроить ngrok вместо Cloudflare")
    ngrok_command.add_argument("--domain", required=True)
    ngrok_command.add_argument("--replace-token", action="store_true")
    key_command = commands.add_parser("key", help="Заменить сохранённый RouterAI API-ключ")
    key_command.add_argument(
        "--clipboard", action="store_true", help="Прочитать ключ из буфера после Enter"
    )
    key_command.add_argument("--account", choices=("admin", "tester"))
    commands.add_parser("diagnose", help="Проверить метаданные без генерации и туннеля")
    commands.add_parser(
        "diagnose-tunnel", help="Проверить HTTPS туннеля и влияние системного прокси"
    )
    for name in ("build", "revoke", "extend"):
        command = commands.add_parser(name)
        command.add_argument("id")
        if name == "extend":
            command.add_argument("--days", type=int, default=30)
    commands.add_parser("list")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Запуск хоста и сборка требуют Windows владельца.")
    root = Path(os.environ["LOCALAPPDATA"]) / "DND-NCFU-Host"
    root.mkdir(parents=True, exist_ok=True)
    # Budget is lifetime across all issued grants. A new grant does not reset it.
    store = (
        None
        if args.command
        in {"key", "diagnose", "diagnose-tunnel", "ngrok", "update-ngrok", "build-exe"}
        else (AccountStore if (root / "account-mode.json").exists() else Store)(
            root / "access.sqlite3",
            global_budget=600_000_000
            if args.command == "accounts" or (root / "account-mode.json").exists()
            else 100_000_000,
        )
    )
    try:
        if args.command == "accounts":
            with host_lock(root):
                setup_accounts(root, store)
        elif args.command == "update-ngrok":
            from scripts.ngrok_host import update_agent

            with host_lock(root):
                update_agent(root)
        elif args.command == "ngrok":
            from scripts.ngrok_host import configure

            configure(root, args.domain, load_secret, save_secret, replace=args.replace_token)
        elif args.command == "diagnose-tunnel":
            report = diagnose_tunnel(root)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 2
        elif args.command == "diagnose":
            key = load_secret(root / "routerai-key.bin")
            if not key:
                raise ValueError("Ключ не найден. Сначала выполните tester_host.cmd key.")
            report = diagnose_provider(Upstream(key))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 2
        elif args.command == "key":
            account = args.account
            if not account and (root / "account-mode.json").exists():
                account = input("Для какой учётной записи меняем ключ (admin/tester): ").strip()
                if account not in {"admin", "tester"}:
                    raise ValueError("Укажите admin или tester.")
            if args.clipboard:
                if account:
                    replace_owner_key(root, from_clipboard=True, account=account)
                else:
                    replace_owner_key(root, from_clipboard=True)
            else:
                if account:
                    replace_owner_key(root, account=account)
                else:
                    replace_owner_key(root)
        elif args.command == "start":
            with host_lock(root):
                host(root, store)
        elif args.command == "build-exe":
            build_owner()
        elif args.command == "build":
            build(root, store, args.id)
        elif args.command == "revoke":
            store.revoke(args.id)
            print("Допуск отозван. Новые обращения будут отклонены.")
        elif args.command == "extend":
            store.extend(args.id, args.days)
            print("Срок продлён без сброса расходов и без нового Setup.")
        else:
            rows = [
                {
                    "tester": row["id"],
                    "budget_rub": row["budget"] / 1e6,
                    "committed_rub": row["committed"] / 1e6,
                    "expires_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(row["expires"])),
                    "revoked": bool(row["revoked"]),
                    "calls": row["calls"],
                }
                for row in store.summary()
            ]
            print(json.dumps(rows, indent=2))
        return 0
    except KeyboardInterrupt:
        print("Хост остановлен.")
        return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print(
            "Операция остановлена. Проверьте инструменты, GitHub-доступ и состояние хоста. "
            "Секреты и ответы провайдера не выводятся.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
