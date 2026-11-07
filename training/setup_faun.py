"""Consent-driven Windows Ollama/Faun setup; fixed loopback, official installer only."""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from rpg_vkr.narrative.local_models import local_models
from training.hardware_preflight import collect
from training.ollama_probe import FAUN_MODEL, request

INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
MODEL_BYTES = 7_500_000_000


def installed_model(tags):
    return next(
        (
            m
            for m in tags.get("models", [])
            if m.get("name", "").casefold() == FAUN_MODEL.casefold()
            and m["name"] in local_models(tags)
        ),
        None,
    )


def assess(hardware, *, installed=False):
    memory = hardware.get("memory", {})
    reasons = []
    if memory.get("total_bytes", 0) < 15 * 1024**3:
        reasons.append("Требуется примерно16ГБ физической памяти.")
    if memory.get("available_bytes", 0) < 9 * 1024**3:
        reasons.append("Недостаточно свободной RAM: закройте браузер и тяжёлые программы.")
    if (
        not installed
        and hardware.get("free_model_disk_bytes", hardware.get("free_disk_bytes", 0))
        < 2 * MODEL_BYTES + 2 * 1024**3
    ):
        reasons.append(
            "На диске моделей нужно не менее17ГБ свободного места для загрузки и временных файлов."
        )
    return reasons


def local_host_allowed(value):
    return not value or value.lower().rstrip("/") in (
        "127.0.0.1:11434",
        "http://127.0.0.1:11434",
        "localhost:11434",
        "http://localhost:11434",
    )


def setup(host, *, interactive=False, check_only=False):
    report = {
        "schema": "faun-setup-v1",
        "observed_at": datetime.now(UTC).isoformat(),
        "model": FAUN_MODEL,
        "status": "CHECKING",
        "events": [],
        "weights_downloaded": False,
        "training_started": False,
        "game_quality": "REQUIRES_GAME_BENCHMARK",
    }
    if not local_host_allowed(host.environment_host()):
        report.update(
            status="BLOCKED_BINDING",
            help="OLLAMA_HOST указывает не на loopback. Настройка не "
            "изменена; проверьте её вручную.",
        )
        return report
    hardware = host.hardware()
    report["hardware"] = hardware
    ollama = host.find_ollama()
    try:
        tags = host.api("/api/tags")
    except (OSError, ValueError):
        tags = {"models": []}
    existing = installed_model(tags)
    reasons = assess(hardware, installed=bool(existing))
    if reasons:
        report.update(status="BLOCKED_RESOURCES", help=reasons)
        return report
    if not ollama and not existing:
        if (
            check_only
            or not interactive
            or not host.confirm(
                "Ollama не найдена. Скачать официальный установщик и открыть "
                "его? Установка будет видна на экране."
            )
        ):
            report.update(
                status="NEEDS_OLLAMA",
                help="Установка не выполнена. Официальный источник: "
                "https://ollama.com/download/windows",
            )
            return report
        host.install_ollama()
        report["events"].append("official_installer_opened_after_confirmation")
        ollama = host.find_ollama()
        if not ollama:
            report.update(
                status="RESTART_SETUP",
                help="Завершите видимый установщик Ollama и запустите мастер ещё раз.",
            )
            return report
    if not host.service_ready():
        if (
            check_only
            or not interactive
            or not host.confirm(
                "Запустить локальный сервис Ollama на127.0.0.1:11434? "
                "Внешний доступ и firewall не изменяются."
            )
        ):
            report.update(
                status="NEEDS_SERVICE",
                help="Откройте Ollama через меню Пуск, затем повторите проверку.",
            )
            return report
        host.start_service(ollama)
        if not host.service_ready(wait=True):
            report.update(
                status="BLOCKED_SERVICE",
                help="Порт11434 недоступен. Проверьте запущенную Ollama; не "
                "открывайте порт во внешнюю сеть.",
            )
            return report
    tags = host.api("/api/tags")
    existing = installed_model(tags)
    if not existing:
        if (
            check_only
            or not interactive
            or not host.confirm(
                "Загрузить Faun Q4_K_M, около7.5ГБ, из "
                "limloop/MN-12B-Faun-RP-RU-GGUF? Это большая загрузка. [y/N]"
            )
        ):
            report.update(
                status="NEEDS_MODEL",
                help="Модель не скачивалась. Повторный запуск безопасен; "
                "подтверждение требуется отдельно.",
            )
            return report
        host.pull(ollama, FAUN_MODEL)
        report["weights_downloaded"] = True
        existing = installed_model(host.api("/api/tags"))
        if existing is None:
            raise ValueError("Ollama не вернула точное имя установленной модели.")
    report["installed"] = {k: existing.get(k) for k in ("name", "digest", "size")}
    if (
        not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", existing.get("digest", ""))
        or type(existing.get("size")) is not int
        or existing["size"] <= 0
    ):
        report.update(
            status="BLOCKED_MODEL_IDENTITY", help="Ollama не подтвердила digest и размер модели."
        )
        return report
    details = host.api("/api/show", {"model": existing["name"]})
    quant = details.get("details", {}).get("quantization_level")
    if quant != "Q4_K_M":
        report.update(
            status="BLOCKED_MODEL_IDENTITY",
            help="Квантовка не подтверждена как Q4_K_M; повторная загрузка "
            "автоматически не запускается.",
        )
        return report
    report["quantization"] = quant
    if check_only:
        report["status"] = "INSTALLED_NOT_BENCHMARKED"
        return report
    if not interactive or not host.confirm(
        "Отправить короткий локальный тест на русском? На CPU ответ может занять несколько минут."
    ):
        report["status"] = "INSTALLED_NOT_BENCHMARKED"
        return report
    started = time.perf_counter()
    memory_before = getattr(host, "memory_usage", lambda: None)()
    reply = host.api(
        "/api/chat",
        {
            "model": existing["name"],
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": "Ответь по-русски одним предложением: обычная метла без "
                    "магии не летает.",
                }
            ],
            "options": {
                "num_ctx": 2048,
                "num_predict": 64,
                "temperature": 0,
                "seed": 37,
                "num_thread": 4,
            },
        },
    )
    text = reply.get("message", {}).get("content", "")
    duration = reply.get("eval_duration", 0) / 1e9
    report["smoke"] = {
        "elapsed_seconds": time.perf_counter() - started,
        "load_seconds": reply.get("load_duration", 0) / 1e9,
        "tokens": reply.get("eval_count"),
        "tokens_per_second": reply.get("eval_count", 0) / duration if duration else None,
        "response": text,
        "done": reply.get("done"),
        "context_tokens": 2048,
        "ollama_working_set_before": memory_before,
        "ollama_working_set_after": getattr(host, "memory_usage", lambda: None)(),
    }
    report["status"] = (
        "LOCAL_SMOKE_OK_GAME_EVALUATION_REQUIRED"
        if text and reply.get("done")
        else "BLOCKED_RESPONSE"
    )
    report["help"] = (
        "В DND-NCFU откройте настройки мастера, выберите локальную "
        "модель и обновите список. Затем выполните игровой бенчмарк."
    )
    return report


class WindowsHost:
    def environment_host(self):
        return os.environ.get("OLLAMA_HOST", "")

    def hardware(self):
        data = collect(scope="owner_laptop")
        model_dir = Path(os.environ.get("OLLAMA_MODELS", str(Path.home() / ".ollama/models")))
        if str(model_dir).startswith("\\\\"):
            raise ValueError("Сетевое хранилище моделей не поддержано установщиком.")
        while not model_dir.exists():
            model_dir = model_dir.parent
        data["free_model_disk_bytes"] = shutil.disk_usage(model_dir).free
        return data

    def find_ollama(self):
        paths = [
            shutil.which("ollama"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"),
        ]
        return next((p for p in paths if p and Path(p).is_file()), None)

    def api(self, path, body=None):
        return request(path, body, timeout=600 if path == "/api/chat" else 5)

    def confirm(self, question):
        return input(question + " [да/НЕТ]: ").strip().casefold() in ("да", "д", "yes", "y")

    def memory_usage(self):
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[long]((Get-Process -Name 'ollama','ollama app','ollama_llama_server' "
                "-ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return (
            int(result.stdout.strip())
            if result.returncode == 0 and result.stdout.strip().isdigit()
            else None
        )

    def install_ollama(self):
        destination = Path(os.environ.get("TEMP", str(Path.home()))) / (
            "dnd-ollama-" + str(time.time_ns()) + ".exe"
        )
        print("Скачивается официальный установщик Ollama. Веса Faun пока не загружаются.")
        with (
            urllib.request.urlopen(INSTALLER_URL, timeout=60) as source,
            destination.open("xb") as target,
        ):
            size = 0
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > 2 * 1024**3:
                    raise ValueError("Установщик превысил ограничение размера.")
                target.write(block)
        # The file path is an environment value, never evaluated as script.
        script = (
            "$s=Get-AuthenticodeSignature -LiteralPath $env:DND_OLLAMA_INSTALLER; "
            "if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject "
            "-notmatch 'Ollama'){exit 2}; "
            "$p=Start-Process -FilePath $env:DND_OLLAMA_INSTALLER -Wait -PassThru; exit $p.ExitCode"
        )
        env = os.environ.copy()
        env["DND_OLLAMA_INSTALLER"] = str(destination)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            check=True,
        )

    def service_ready(self, wait=False):
        for _ in range(30 if wait else 1):
            try:
                if isinstance(self.api("/api/version").get("version"), str):
                    return True
            except (OSError, ValueError):
                pass
            if wait:
                time.sleep(1)
        return False

    def start_service(self, ollama):
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "127.0.0.1:11434"
        subprocess.Popen(
            [ollama, "serve"],
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

    def pull(self, ollama, model):
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "127.0.0.1:11434"
        subprocess.run([ollama, "pull", model], env=env, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    report_path = a.report or Path("../DND-NCFU-data/diagnostics") / (
        "faun-setup-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + ".json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        raise ValueError("Отчёт уже существует; выберите новое имя.")
    try:
        if os.name != "nt":
            raise ValueError(
                "Этот установщик запускается только на Windows; cloud не "
                "является ноутбуком владельца."
            )
        result = setup(WindowsHost(), interactive=a.interactive, check_only=a.check_only)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = {
            "status": "FAILED",
            "error_category": type(error).__name__,
            "help": "Установка не подтверждена. Проверьте официальный "
            "установщик/подключение и повторите мастер; ключи и "
            "настройки защиты не меняйте.",
            "training_started": False,
        }
    with report_path.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(result["status"])
    print(result.get("help", ""))
    print("Отчёт: " + str(report_path))
    if result["status"] not in (
        "LOCAL_SMOKE_OK_GAME_EVALUATION_REQUIRED",
        "INSTALLED_NOT_BENCHMARKED",
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
