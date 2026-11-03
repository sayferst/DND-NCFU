"""No weights or CUDA needed to verify refusal-to-fabricate and model profiles."""

import json
from pathlib import Path

import pytest

from rpg_vkr.narrative.strategic_critic import fit, inspect
from training.model_profiles import template_arguments, validate_local, validate_lora_modules
from training.ollama_probe import FAUN_MODEL, probe
from training.train_lora import preflight


def test_faun_uses_own_versioned_profile_without_changing_qwen():
    faun = json.loads(Path("training/configs/faun_qlora_v1.json").read_text(encoding="utf-8"))
    qwen = json.loads(Path("training/configs/one_qlora_config.json").read_text(encoding="utf-8"))
    assert template_arguments(faun) == {}
    assert template_arguments(qwen) == {"enable_thinking": False}
    assert qwen["model_id"] == "Qwen/Qwen3-4B"
    assert len(faun["revision"]) == 40 and len(faun["chat_template_sha256"]) == 64
    assert preflight(faun).startswith("BLOCKED_DATA")


def test_no_implicit_model_pull_and_installed_digest_is_recorded():
    paths = []

    def missing(path, body=None):
        paths.append(path)
        return {"models": []}

    assert probe(requester=missing, measure=True)["status"] == "BLOCKED_MODEL"
    assert paths == ["/api/tags"]
    result = probe(
        requester=lambda *a: {"models": [{"name": FAUN_MODEL, "digest": "unit-test-digest"}]}
    )
    assert result["installed_digest"] == "unit-test-digest"
    assert result["measurements"] == [] and result["training_steps"] == 0


def test_architecture_and_lora_layers_are_actually_checked(tmp_path):
    (tmp_path / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
    with pytest.raises(ValueError, match="architecture"):
        validate_local({"model_family": "faun_mistral_nemo", "model_path": str(tmp_path)})

    class WrongLayers:
        def named_modules(self):
            return [("model.unrelated", None)]

    with pytest.raises(ValueError, match="LoRA"):
        validate_lora_modules(WrongLayers(), {"target_modules": ["q_proj"]})


def test_critic_never_invents_human_labels_or_training():
    with pytest.raises(ValueError, match="BLOCKED_DATA"):
        fit([])
    issues = inspect(
        {"committed": True, "free_attempt": {"mode": "ATTEMPT_WITHOUT_TARGET_SUCCESS"}, "dice": []},
        "Монеты появились",
    )
    assert issues[0]["code"] == "UNCONFIRMED_CAPABILITY"


def test_existing_ollama_client_accepts_faun_tag_over_real_loopback_http(qt_app):
    from test_local_narrator import local_server, wait_for

    from rpg_vkr.application import Session
    from rpg_vkr.narrative.context import build_frame
    from rpg_vkr.narrative.ollama import OllamaClient

    with local_server() as (url, requests):
        client = OllamaClient(base_url=url)
        client.models = (FAUN_MODEL,)
        outputs, failures = [], []
        client.narration_ready.connect(outputs.append)
        client.failed.connect(failures.append)
        client.narrate(build_frame(Session()), FAUN_MODEL)
        wait_for(qt_app, lambda: bool(outputs or failures))
        assert outputs and not failures
        body = next(body for path, body in requests if path == "/api/chat")
        assert body["model"] == FAUN_MODEL and "think" not in body
        client.cancel()


def test_installed_local_narrator_opens_modern_gate_without_cloud(window):
    from test_free_actions_pipeline import campaign

    from rpg_vkr.ui.cloud_gate import local_ready

    window._session = campaign()
    window._legacy_controls = False
    window.ai_provider.setCurrentIndex(window.ai_provider.findData("local"))
    window.enable_local_narrator.setChecked(True)
    window.ai_chat.setChecked(True)
    window.local_model.addItem(FAUN_MODEL)
    window.local_model.setCurrentText(FAUN_MODEL)
    window.ollama.models = (FAUN_MODEL,)
    assert local_ready(window)
    window.ollama.models = ()
    assert not local_ready(window)


def test_model_comparison_preserves_missing_conditions_and_export_needs_approval(tmp_path):
    from training.compare_models import compare
    from training.merge_gguf import verify

    result = compare([])
    assert all(
        r["status"] == "NOT_RUN" and r["metrics"] is None for r in result["conditions"].values()
    )
    path = tmp_path / "deployment.json"
    path.write_text('{"approved_for_runtime":false}', encoding="utf-8")
    with pytest.raises(ValueError, match="BLOCKED_APPROVAL"):
        verify(path, {}, tmp_path, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def test_windows_preflight_distinguishes_integrated_graphics_from_cuda(monkeypatch):
    from training import hardware_preflight as hardware

    monkeypatch.setattr(hardware.platform, "system", lambda: "Windows")

    def output(args):
        if args[0] == "nvidia-smi":
            return None
        if "Win32_VideoController" in args[-1]:
            return '{"name":"Intel Iris Xe","driver":"test","reported_adapter_bytes":134217728}'
        return '{"total_bytes":17179869184,"available_bytes":10737418240}'

    monkeypatch.setattr(hardware, "command", output)
    report = hardware.collect(scope="owner_laptop")
    assert report["display_adapters"][0]["name"] == "Intel Iris Xe"
    assert report["gpus"] == [] and report["training_status"] == "BLOCKED_HARDWARE"
