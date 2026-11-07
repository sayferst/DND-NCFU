from training.ollama_probe import FAUN_MODEL
from training.setup_faun import setup


class Host:
    def __init__(self, *, installed=False, executable=True, running=True, answers=(), memory=12):
        self.installed, self.executable, self.running = installed, executable, running
        self.answers = iter(answers)
        self.calls = []
        self.memory = memory

    def environment_host(self):
        return ""

    def hardware(self):
        return {
            "memory": {"total_bytes": 16 * 1024**3, "available_bytes": self.memory * 1024**3},
            "free_model_disk_bytes": 40 * 1024**3,
        }

    def find_ollama(self):
        return "ollama.exe" if self.executable else None

    def confirm(self, q):
        self.calls.append(("confirmation", q))
        return next(self.answers, False)

    def api(self, path, body=None):
        self.calls.append((path, body))
        if not self.running:
            raise OSError("offline")
        if path == "/api/tags":
            return {
                "models": [{"name": FAUN_MODEL, "digest": "a" * 64, "size": 7500000000}]
                if self.installed
                else []
            }
        if path == "/api/show":
            return {"details": {"quantization_level": "Q4_K_M"}}
        if path == "/api/chat":
            return {
                "message": {"content": "Обычная метла не летает."},
                "done": True,
                "eval_count": 8,
                "eval_duration": 2 * 10**9,
            }
        return {"version": "test"}

    def install_ollama(self):
        self.calls.append(("install",))
        self.executable = True

    def service_ready(self, wait=False):
        return self.running

    def start_service(self, path):
        self.calls.append(("start",))
        self.running = True

    def pull(self, path, model):
        self.calls.append(("pull", model))
        self.installed = True


def test_declining_install_and_download_does_not_mutate_machine():
    h = Host(executable=False, answers=[False])
    assert setup(h, interactive=True)["status"] == "NEEDS_OLLAMA"
    assert not any(c[0] in ("install", "start", "pull") for c in h.calls)
    h = Host(answers=[False])
    assert setup(h, interactive=True)["status"] == "NEEDS_MODEL"
    assert not any(c[0] == "pull" for c in h.calls)


def test_existing_model_is_not_downloaded_again_and_smoke_is_local():
    h = Host(installed=True, answers=[True])
    r = setup(h, interactive=True)
    assert r["status"] == "LOCAL_SMOKE_OK_GAME_EVALUATION_REQUIRED"
    assert r["smoke"]["tokens_per_second"] == 4
    assert not any(c[0] in ("install", "pull") for c in h.calls)
    assert r["training_started"] is False


def test_every_mutating_stage_has_its_own_confirmation_and_repeat_is_safe():
    h = Host(executable=False, running=False, answers=[True, True, True, True])
    r = setup(h, interactive=True)
    assert r["weights_downloaded"] and r["status"] == "LOCAL_SMOKE_OK_GAME_EVALUATION_REQUIRED"
    assert [c[0] for c in h.calls].count("confirmation") == 4
    h.calls.clear()
    r = setup(h, check_only=True)
    assert r["status"] == "INSTALLED_NOT_BENCHMARKED"
    assert not any(c[0] in ("install", "pull", "start", "/api/chat") for c in h.calls)


def test_resource_failure_and_external_binding_never_start_download():
    h = Host(memory=4, answers=[True] * 4)
    assert setup(h, interactive=True)["status"] == "BLOCKED_RESOURCES"
    assert not any(c[0] in ("install", "pull", "start") for c in h.calls)
    h = Host()
    h.environment_host = lambda: "0.0.0.0:11434"
    assert setup(h, interactive=True)["status"] == "BLOCKED_BINDING"
    assert not h.calls
