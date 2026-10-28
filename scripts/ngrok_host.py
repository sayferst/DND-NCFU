"""Owner-only ngrok agent. Authtoken is environment-only and never enters the Setup."""

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from scripts.tunnel_supervision import RestartTunnel

MIN_VERSION = (3, 39, 12)  # Config/flags verified on this official agent release.


def version(agent):
    try:
        result = subprocess.run(
            [agent, "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        match = re.fullmatch(r"ngrok version (\d+)\.(\d+)\.(\d+)(?:[^\r\n]*)\s*", result.stdout)
        if result.returncode == 0 and match:
            return tuple(int(part) for part in match.groups())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    raise ValueError("Не удалось определить версию ngrok. Выполните tester_host.cmd update-ngrok.")


def require_supported(agent):
    found = version(agent)
    if found < MIN_VERSION:
        raise ValueError(
            "Установлен старый ngrok "
            + ".".join(map(str, found))
            + ". Нужен 3.39.12 или новее. Выполните tester_host.cmd update-ngrok, затем start. "
            "Это несовместимость агента; настройки VPN и ключи менять не требуется."
        )
    return found


def update_agent(root, archive_path=None):
    # A private portable copy: never modify a package-manager-owned executable.
    target = root / "ngrok-agent" / "ngrok.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    from scripts.ngrok_download import download_agent

    print(
        "Проверяю локальный ZIP ngrok…"
        if archive_path
        else "Загружаю официальный ngrok и проверяю подпись Windows…",
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="ngrok-update-", dir=root) as temporary:
        candidate = Path(temporary) / "ngrok.exe"
        if archive_path is None:
            download_agent(candidate)
        else:
            download_agent(candidate, archive_path=archive_path)
        found = require_supported(str(candidate))
        try:
            os.replace(candidate, target)
        except OSError:
            raise ValueError(
                "Не удалось заменить ngrok. Остановите хост и повторите обновление."
            ) from None
        print("ngrok обновлён: " + ".".join(map(str, found)) + ". Выполните tester_host.cmd start.")


def domain_name(value):
    value = value.strip().lower().removeprefix("https://").rstrip("/")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.ngrok-free\.(?:dev|app)", value):
        raise ValueError("Укажите выданный ngrok домен вида имя.ngrok-free.dev без пути и порта.")
    return value


def executable():
    found = shutil.which("ngrok.exe") or shutil.which("ngrok")
    candidates = [Path(found)] if found else []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.insert(0, Path(local) / "DND-NCFU-Host/ngrok-agent/ngrok.exe")
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            base = Path(root)
            candidates.extend(
                [
                    base / "Microsoft/WinGet/Links/ngrok.exe",
                    base / "WinGet/Links/ngrok.exe",
                    base / "ngrok/ngrok.exe",
                ]
            )
            for packages in (base / "Microsoft/WinGet/Packages", base / "WinGet/Packages"):
                candidates.extend(packages.glob("Ngrok.Ngrok_*/ngrok.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise ValueError(
        "ngrok не найден. Установите: winget install --id Ngrok.Ngrok --exact --source winget"
    )


def load_settings(root):
    path = root / "tunnel.json"
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 2048:
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"))
        if set(value) != {"provider", "domain"} or value["provider"] != "ngrok":
            raise ValueError
        return {"provider": "ngrok", "domain": domain_name(value["domain"])}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError(
            "Повреждены настройки туннеля. Повторите tester_host.cmd ngrok --domain ДОМЕН."
        ) from None


def validate_token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{20,512}", value):
        raise ValueError("Нужен ngrok Authtoken без пробелов и команд. Настройки не изменены.")
    return value


def configure(root, domain, load_secret, save_secret, *, replace=False):
    domain = domain_name(domain)
    executable()  # Fail before reading/replacing owner credentials if agent is missing.
    path = root / "ngrok-token.bin"
    token = "" if replace else load_secret(path)
    if not token:
        token = input("Введите ngrok Authtoken (ввод виден только в этой консоли): ").strip()
    validate_token(token)
    save_secret(path, token)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump({"provider": "ngrok", "domain": domain}, file)
        temporary.replace(root / "tunnel.json")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    print("ngrok настроен. Запустите tester_host.cmd start. RouterAI-ключ и допуски сохранены.")


AGENT_CONFIG = {
    "version": "3",
    "agent": {"web_addr": False, "update_check": False},
}


def command(agent, port, domain, config):
    return [
        agent,
        "http",
        f"http://127.0.0.1:{int(port)}",
        "--url",
        "https://" + domain_name(domain),
        "--config",
        str(config),
        "--log=stdout",
        "--log-format=json",
        "--inspect=false",
    ]


def read_output(stream, connected, endpoint, failures=None):
    reported = set()
    try:
        for line in stream:
            if len(line) > 8192:
                continue
            try:
                value = json.loads(line)
                if (
                    isinstance(value, dict)
                    and value.get("msg") == "started tunnel"
                    and value.get("url") == endpoint
                ):
                    connected.put(True)
            except (ValueError, TypeError, RecursionError):
                pass
            # Only a numeric documented vendor error code is allowed out of agent logs.
            match = re.search(r"\bERR_NGROK_\d{1,6}\b", line)
            if match and match[0] not in reported:
                print(
                    "ngrok: " + match[0] + ". Проверьте Authtoken, домен и лимиты в кабинете.",
                    flush=True,
                )
                reported.add(match[0])
                if failures is not None:
                    failures.append(
                        "ngrok отклонил запуск: "
                        + match[0]
                        + ". Проверьте причину в кабинете ngrok."
                    )
            lower = line.lower()
            if failures is not None and (
                "unknown flag" in lower
                or "unknown shorthand flag" in lower
                or "error reading configuration" in lower
                or "unrecognized configuration version" in lower
            ):
                failures.append(
                    "ngrok не принял параметры или config. Выполните tester_host.cmd update-ngrok."
                )
    finally:
        connected.put(False)


@contextmanager
def running(root, agent, port, domain, token):
    domain = domain_name(domain)
    require_supported(agent)  # Fatal incompatibility must not enter the reconnect loop.
    validate_token(token)
    config = None
    process = None
    reader = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".yml", dir=root, delete=False
        ) as file:
            config = Path(file.name)
            json.dump(AGENT_CONFIG, file)  # JSON is valid YAML; contains no authtoken.
        environment = os.environ.copy()
        environment["NGROK_AUTHTOKEN"] = token
        process = subprocess.Popen(
            command(agent, port, domain, config),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        connected = queue.Queue()
        failures = []
        endpoint = "https://" + domain
        reader = threading.Thread(
            target=read_output, args=(process.stdout, connected, endpoint, failures), daemon=True
        )
        reader.start()
        try:
            ready = connected.get(timeout=90)
        except queue.Empty:
            raise RestartTunnel("ngrok не подтвердил запуск HTTPS endpoint за90с.") from None
        if not ready or process.poll() is not None:
            if failures:
                raise ValueError(failures[-1])
            raise RestartTunnel(
                "ngrok завершился до запуска HTTPS endpoint; смотрите код ERR_NGROK выше."
            )
        yield process, endpoint
    finally:
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
        if config:
            config.unlink(missing_ok=True)
