"""ngrok agent setup/lifecycle and client policy with fake processes, no real tokens."""

import io
import json
import queue
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rpg_vkr.gateway_http import gateway_headers, health_interval, job_poll_ms
from scripts import ngrok_host as ngrok
from scripts import tester_host as host

DOMAIN = "test-ngrok.ngrok-free.dev"
TOKEN = "fake-ngrok-authtoken-123456789"


@pytest.mark.parametrize("domain", ["test.ngrok-free.app", DOMAIN])
def test_free_domains_get_gateway_header_and_bounded_idle_usage(domain):
    url = "https://" + domain + "/api/v1"
    assert ngrok.domain_name(url.removesuffix("/api/v1")) == domain
    assert gateway_headers(url) == {"ngrok-skip-browser-warning": "1"}
    assert 30 * 86400 / health_interval(url) <= 10000
    assert job_poll_ms(url) >= 10000


@pytest.mark.parametrize(
    "domain",
    [
        "http://test.ngrok-free.dev",
        "test.ngrok-free.dev.evil",
        "user@test.ngrok-free.dev",
        "test.ngrok-free.dev:443",
        "test.ngrok-free.dev/path",
        "--bad.ngrok-free.dev",
    ],
)
def test_domain_cannot_inject_flags_credentials_paths_or_other_hosts(domain):
    with pytest.raises(ValueError):
        ngrok.domain_name(domain)


def test_gateway_hints_do_not_affect_model_provider_or_cloudflare():
    for url in (
        "https://routerai.ru/api/v1",
        "https://test.trycloudflare.com/api/v1",
        "https://test.ngrok-free.dev.evil",
    ):
        assert not gateway_headers(url)
        assert job_poll_ms(url) == 600


def test_configure_persists_only_public_domain_and_protected_authtoken(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ngrok, "executable", lambda: "ngrok.exe")
    monkeypatch.setattr("builtins.input", lambda _: TOKEN)
    protected = {"routerai-key.bin": "owner-model-key", "activation-tester1.bin": "existing grant"}
    ngrok.configure(
        tmp_path, DOMAIN, lambda path: "", lambda path, value: protected.update({path.name: value})
    )
    assert ngrok.load_settings(tmp_path) == {"provider": "ngrok", "domain": DOMAIN}
    assert TOKEN not in (tmp_path / "tunnel.json").read_text() + capsys.readouterr().out
    assert protected == {
        "routerai-key.bin": "owner-model-key",
        "activation-tester1.bin": "existing grant",
        "ngrok-token.bin": TOKEN,
    }


def test_bad_token_replacement_preserves_existing_configuration(tmp_path, monkeypatch):
    initial = json.dumps({"provider": "ngrok", "domain": DOMAIN})
    (tmp_path / "tunnel.json").write_text(initial)
    monkeypatch.setattr(ngrok, "executable", lambda: "ngrok.exe")
    monkeypatch.setattr("builtins.input", lambda _: "ngrok config add-authtoken wrong")
    with pytest.raises(ValueError):
        ngrok.configure(
            tmp_path,
            DOMAIN,
            lambda path: TOKEN,
            lambda *a: pytest.fail("Do not overwrite token"),
            replace=True,
        )
    assert (tmp_path / "tunnel.json").read_text() == initial


def test_agent_gets_token_only_in_environment_and_cleans_up_on_ctrl_c(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(ngrok, "require_supported", lambda agent: ngrok.MIN_VERSION)
    monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)

    class Process:
        returncode = None

        def __init__(self):
            self.stdout = io.StringIO(
                json.dumps({"msg": "started tunnel", "url": "https://" + DOMAIN}) + "\n"
            )
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0
            self.terminated = True

        def wait(self, timeout):
            return self.returncode

    process = Process()

    def start(command, **kwargs):
        seen.update(command=command, **kwargs)
        config = json.loads(
            Path(command[command.index("--config") + 1]).read_text(encoding="utf-8")
        )
        assert config["agent"]["web_addr"] is False
        assert TOKEN not in json.dumps(config) and TOKEN not in " ".join(command)
        assert "--inspect=false" in command and kwargs["env"]["NGROK_AUTHTOKEN"] == TOKEN
        return process

    monkeypatch.setattr(ngrok.subprocess, "Popen", start)
    with pytest.raises(KeyboardInterrupt):
        with ngrok.running(tmp_path, "ngrok.exe", 1234, DOMAIN, TOKEN) as (child, endpoint):
            assert child is process and endpoint == "https://" + DOMAIN
            raise KeyboardInterrupt
    assert process.terminated and not list(tmp_path.iterdir())
    assert "NGROK_AUTHTOKEN" not in ngrok.os.environ


def test_agent_error_logs_never_echo_raw_private_values(capsys):
    text = "ERROR ERR_NGROK_105 private-path " + TOKEN
    connected = queue.Queue()
    ngrok.read_output(io.StringIO(text + "\n"), connected, "https://" + DOMAIN)
    output = capsys.readouterr().out
    assert "ERR_NGROK_105" in output and TOKEN not in output and "private-path" not in output
    assert connected.get_nowait() is False


def test_ngrok_start_never_launches_cloudflare_or_runs_edge_dns(tmp_path, monkeypatch):
    (tmp_path / "tunnel.json").write_text(json.dumps({"provider": "ngrok", "domain": DOMAIN}))
    monkeypatch.setattr(ngrok, "executable", lambda: "ngrok.exe")
    monkeypatch.setattr(host, "cloudflared_path", lambda: pytest.fail("Do not use Cloudflare"))
    monkeypatch.setattr(host, "private_key", lambda root: Ed25519PrivateKey.generate())
    monkeypatch.setattr(
        host,
        "load_secret",
        lambda path: TOKEN if path.name == "ngrok-token.bin" else "fake-api-key",
    )
    monkeypatch.setattr(host, "check_provider", lambda gateway: None)
    from scripts import tunnel_dns

    monkeypatch.setattr(
        tunnel_dns, "resolve_tunnel_edges", lambda: pytest.fail("Do not run Cloudflare DNS")
    )
    closed = []

    class Server:
        server_port = 1234

        def __init__(self, *args):
            pass

        def serve_forever(self):
            pass

        def shutdown(self):
            closed.append(True)

        def server_close(self):
            pass

    @contextmanager
    def running(root, agent, port, domain, token):
        assert (agent, port, domain, token) == ("ngrok.exe", 1234, DOMAIN, TOKEN)
        yield object(), "https://" + DOMAIN

    def serve(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(host, "Server", Server)
    monkeypatch.setattr(ngrok, "running", running)
    monkeypatch.setattr(host, "serve_public_endpoint", serve)
    with pytest.raises(KeyboardInterrupt):
        host.host(tmp_path, object())
    assert closed == [True]


def test_cli_configuration_does_not_open_grant_database(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(
        host, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)})
    )
    monkeypatch.setattr(host, "Store", lambda *a, **k: pytest.fail("No quota database"))
    calls = []
    monkeypatch.setattr(ngrok, "configure", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["tester_host.py", "ngrok", "--domain", DOMAIN])
    assert host.main() == 0 and calls[0][0][1] == DOMAIN
