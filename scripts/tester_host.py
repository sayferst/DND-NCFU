"""Owner-only Windows host: signed Quick Tunnel discovery and personalized Setup."""

import argparse
import base64
import getpass
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
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from rpg_vkr.discovery import (  # noqa: E402
    NoRedirect,
    canonical,
    discovery_url,
    fetch,
    public_endpoint,
)
from rpg_vkr.storage.connection import load_secret, save_secret  # noqa: E402
from server.gateway import (  # noqa: E402
    FLUX,
    RECRAFT,
    TEXT_MODEL,
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
    request = urllib.request.Request(public_endpoint(endpoint) + "/health")
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as reply:
        if reply.status != 200 or json.loads(reply.read(2048)) != {
            "service": "dnd-gateway",
            "protocol": 1,
            "async_jobs": True,
        }:
            raise ValueError("Шлюз не прошёл проверку доступности.")


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


def metadata_failure(error, label):
    messages = {
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
    reason = messages.get(error.code)
    if reason is None:
        match = re.fullmatch(r"upstream_http_([1-5][0-9]{2})", error.code)
        reason = (
            f"RouterAI вернул HTTP {match[1]} при проверке метаданных. Повторите запуск позже."
            if match
            else "RouterAI временно не подтвердил метаданные. Повторите запуск позже."
        )
    return ValueError(label + ": " + reason + " Платная генерация не запускалась.")


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
        available = {row["id"] for row in catalog["data"]}
        if not {TEXT_MODEL, RECRAFT, FLUX} <= available:
            raise ValueError
        gateway.validate(
            "chat/completions",
            {
                "model": TEXT_MODEL,
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
    tunnel = cloudflared_path()
    private = private_key(root)
    key = load_secret(root / "routerai-key.bin")
    if not key:
        key = getpass.getpass("Введите RouterAI API-ключ (не отображается): ").strip()
        Upstream(key)  # Validate before protecting; no request is made.
        save_secret(root / "routerai-key.bin", key)
    gateway = Gateway(store, Upstream(key))
    print("Проверяю ключ и каталог RouterAI без генерации…", flush=True)
    check_provider(gateway)
    server = Server(("127.0.0.1", 0), gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = None
    try:
        process = subprocess.Popen(
            [
                tunnel,
                "tunnel",
                "--url",
                f"http://127.0.0.1:{server.server_port}",
                "--no-autoupdate",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        urls = queue.Queue()

        def read():
            for line in process.stdout:
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match:
                    urls.put(match.group())
            urls.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        print("Шлюз запущен только на этом ПК. Ожидание HTTPS-туннеля…", flush=True)
        try:
            endpoint = urls.get(timeout=90)
        except queue.Empty:
            raise ValueError("Туннель не выдал адрес за 90 секунд.") from None
        if not endpoint:
            raise ValueError("cloudflared завершился до выдачи адреса.")
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
        deadline = time.monotonic() + 90
        while True:
            try:
                verified = fetch(DISCOVERY, public_key, previous=sequence)
                if verified["endpoint"] != public_endpoint(endpoint):
                    raise ValueError("Адрес ещё не обновился.")
                check_health(verified["endpoint"])
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise ValueError(
                        "Публичный документ пока не доступен. Повторите start позже."
                    ) from None
                time.sleep(3)
        (root / "host-ready.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "discovery": DISCOVERY,
                    "verification_key": public_key,
                    "sequence": sequence,
                }
            ),
            encoding="utf-8",
        )
        print(
            "Адрес опубликован и подпись проверена. Платных проверок не было.\n"
            "Оставьте это окно открытым. Во втором окне: scripts\\tester_host.cmd build tester1\n"
            "Остановка: Ctrl+C. После перезапуска адрес обновится без нового Setup.",
            flush=True,
        )
        refresh_at = time.monotonic() + 7 * 86400
        while process.poll() is None:
            time.sleep(1)
            if time.monotonic() >= refresh_at:
                sequence += 1
                sequence_path.write_text(str(sequence), encoding="utf-8")
                publish(signed_manifest(private, endpoint, sequence))
                refresh_at = time.monotonic() + 7 * 86400
        raise ValueError("Туннель остановился. Запустите start заново.")
    finally:
        (root / "host-ready.json").unlink(missing_ok=True)
        server.shutdown()
        server.server_close()
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()


def build(root, store, identity):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", identity):
        raise ValueError("Имя допуска: латинские буквы, цифры, _ или -; до60знаков.")
    # Fail before issuing a grant if Inno Setup is missing; no hidden installation.
    compiler = shutil.which("ISCC.exe") or str(
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "Inno Setup 6/ISCC.exe"
    )
    if not Path(compiler).is_file():
        raise ValueError(
            "Нужен Inno Setup6. Команда установки приведена в docs/TESTER_WITHOUT_DOMAIN.md."
        )
    ready = json.loads((root / "host-ready.json").read_text(encoding="utf-8"))
    discovery_url(ready["discovery"])
    verified = fetch(ready["discovery"], ready["verification_key"], previous=ready["sequence"])
    check_health(verified["endpoint"])
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
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=root, delete=False, encoding="utf-8"
        ) as file:
            temporary = Path(file.name)
            json.dump({"code": code}, file)
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
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        setups = sorted((ROOT / "dist").glob("*Setup*.exe"), key=lambda p: p.stat().st_mtime)
        if not setups:
            raise ValueError("Сборщик не создал Setup.")
        destination = ROOT / "dist" / ("Tester-" + identity)
        destination.mkdir(exist_ok=True)
        shutil.copy2(setups[-1], destination / setups[-1].name)
        print("Персональный Setup: " + str(destination / setups[-1].name))
        print("Передавайте только этому человеку. Допуск:100₽/30дней с момента создания.")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start")
    commands.add_parser("key")
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
    store = Store(root / "access.sqlite3", global_budget=100_000_000)
    try:
        if args.command == "key":
            value = getpass.getpass("Новый RouterAI API-ключ (не отображается): ").strip()
            Upstream(value)
            save_secret(root / "routerai-key.bin", value)
            print("Ключ защищён DPAPI. Перезапустите хост для применения.")
        elif args.command == "start":
            with host_lock(root):
                host(root, store)
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
