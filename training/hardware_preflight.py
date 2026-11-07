"""Read-only hardware report. Never installs drivers, models or a CUDA stack."""

import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
        return result.stdout[:16384] if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def collect(*, scope="execution_environment", disk_path="."):
    report = {
        "schema": "dnd-hardware-1",
        "scope": scope,
        "observed_at": datetime.now(UTC).isoformat(),
        "platform": platform.system(),
        "cpu": platform.processor(),
        "logical_cpus": __import__("os").cpu_count(),
        "free_disk_bytes": shutil.disk_usage(disk_path).free,
        "ollama_installed": shutil.which("ollama") is not None,
        "llama_cpp_installed": shutil.which("llama-server") is not None,
        "training_stack_installed": importlib.util.find_spec("torch") is not None,
        "memory": {},
        "gpus": [],
        "gpus_source": "nvidia-smi CUDA candidates, not all display adapters",
        "display_adapters": [],
    }
    if platform.system() == "Linux":
        rows = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
        values = {r.split(":")[0]: int(r.split()[1]) * 1024 for r in rows}
        report["memory"] = {
            "total_bytes": values["MemTotal"],
            "available_bytes": values["MemAvailable"],
        }
    elif platform.system() == "Windows":
        raw = command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$o=Get-CimInstance Win32_OperatingSystem; "
                "@{total_bytes=[long]$o.TotalVisibleMemorySize*1024; "
                "available_bytes=[long]$o.FreePhysicalMemory*1024}|ConvertTo-Json -Compress",
            ]
        )
        if raw:
            report["memory"] = json.loads(raw)
        adapters = command(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "@(Get-CimInstance Win32_VideoController | ForEach-Object {"
                "@{name=$_.Name;driver=$_.DriverVersion;reported_adapter_bytes=[long]$_.AdapterRAM}"
                "}) | ConvertTo-Json -Compress",
            ]
        )
        if adapters:
            values = json.loads(adapters)
            report["display_adapters"] = [values] if isinstance(values, dict) else values
    gpu = command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if gpu:
        for line in gpu.strip().splitlines():
            name, memory, driver = [s.strip() for s in line.split(",")]
            report["gpus"].append({"name": name, "vram_mib": int(memory), "driver": driver})
    report["training_status"] = (
        "REQUIRES_CUDA_BATCH_SMOKE_TEST"
        if report["gpus"] and report["training_stack_installed"]
        else "BLOCKED_HARDWARE"
    )
    report["inference_status"] = "REQUIRES_LOCAL_MODEL_AND_MEASUREMENT"
    report["training_started"] = False
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scope",
        choices=("owner_laptop", "friend_gpu", "execution_environment"),
        default="execution_environment",
    )
    args = parser.parse_args()
    report = collect(scope=args.scope)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["training_status"], "scope": report["scope"]}))


if __name__ == "__main__":
    main()
