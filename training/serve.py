"""Owner-only localhost Ollama-compatible inference for a verified PEFT adapter."""

import argparse
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(config, adapter, port, *, baseline=False):
    from training.model_profiles import validate_local

    validate_local(config)
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if port not in (11434, 11435):
        raise ValueError("Choose the explicitly supported local port11434 or11435")
    if baseline:
        adapter = None
        manifest = {"adapter_sha256": config["revision"]}
    else:
        adapter = Path(adapter)
    manifest = (
        json.loads((adapter / "training-manifest.json").read_text(encoding="utf-8"))
        if adapter
        else manifest
    )
    if adapter and (
        manifest.get("smoke")
        or manifest["global_step"] < 1
        or hashlib.sha256((adapter / "adapter_model.safetensors").read_bytes()).hexdigest()
        != manifest["adapter_sha256"]
    ):
        raise ValueError("No real verified adapter")
    if adapter and manifest.get("model_revision") != config.get("revision"):
        raise ValueError("Adapter belongs to a different base revision")
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_path"], local_files_only=True, trust_remote_code=False
    )
    base = AutoModelForCausalLM.from_pretrained(
        config["model_path"],
        local_files_only=True,
        trust_remote_code=False,
        device_map={"": 0},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=config.get("double_quant", False),
        ),
    )
    model = (
        PeftModel.from_pretrained(base, adapter, local_files_only=True).eval()
        if adapter
        else base.eval()
    )
    model_name = "dnd-base-narrator" if baseline else "dnd-trained-narrator"
    model_size = (
        (adapter / "adapter_model.safetensors").stat().st_size
        if adapter
        else sum(p.stat().st_size for p in Path(config["model_path"]).glob("*.safetensors"))
    )
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, code=200):
            raw = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/api/tags":
                self.send(
                    {
                        "models": [
                            {
                                "name": model_name,
                                "size": model_size,
                                "digest": manifest["adapter_sha256"],
                            }
                        ]
                    }
                )
            else:
                self.send({"error": "not_found"}, 404)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send({"error": "invalid_request"}, 400)
                return
            if self.path != "/api/chat" or not 0 < length <= 256 * 1024:
                self.send({"error": "invalid_request"}, 400)
                return
            if not lock.acquire(blocking=False):
                self.send({"error": "busy"}, 429)
                return
            try:
                body = json.loads(self.rfile.read(length))
                if body.get("model") != model_name:
                    raise ValueError("Requested model is not loaded")
                from training.inference_protocol import generate

                self.send(generate(body, tokenizer, model, config, torch))
            except (ValueError, KeyError, TypeError):
                self.send({"error": "invalid_request"}, 400)
            except Exception:
                self.send({"error": "inference_failed"}, 500)
            finally:
                lock.release()

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--adapter", type=Path)
    mode.add_argument("--baseline", action="store_true")
    p.add_argument("--port", type=int, default=11435)
    a = p.parse_args()
    serve(json.loads(a.config.read_text(encoding="utf-8")), a.adapter, a.port, baseline=a.baseline)


if __name__ == "__main__":
    main()
