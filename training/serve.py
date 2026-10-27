"""Owner-only localhost Ollama-compatible inference for a verified PEFT adapter."""

import argparse
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(config, adapter, port):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    adapter = Path(adapter)
    manifest = json.loads((adapter / "training-manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("smoke")
        or manifest["global_step"] < 1
        or hashlib.sha256((adapter / "adapter_model.safetensors").read_bytes()).hexdigest()
        != manifest["adapter_sha256"]
    ):
        raise ValueError("No real verified adapter")
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_path"], local_files_only=True, trust_remote_code=False
    )
    base = AutoModelForCausalLM.from_pretrained(
        config["model_path"],
        local_files_only=True,
        trust_remote_code=False,
        device_map={"": 0},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16
        ),
    )
    model = PeftModel.from_pretrained(base, adapter, local_files_only=True).eval()
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
                self.send({"models": [{"name": "dnd-trained-narrator"}]})
            else:
                self.send({"error": "not_found"}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/api/chat" or not 0 < length <= 256 * 1024:
                self.send({"error": "invalid_request"}, 400)
                return
            if not lock.acquire(blocking=False):
                self.send({"error": "busy"}, 429)
                return
            try:
                body = json.loads(self.rfile.read(length))
                messages = body["messages"]
                if not isinstance(messages, list) or len(messages) > 12:
                    raise ValueError("Invalid messages")
                inputs = tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    enable_thinking=False,
                    return_tensors="pt",
                ).to(model.device)
                if inputs.shape[1] > 8192:
                    raise ValueError("Context too large")
                limit = body.get("options", {}).get("num_predict", 1024)
                if type(limit) is not int or not 1 <= limit <= 4500:
                    raise ValueError("Output limit")
                with torch.no_grad():
                    output = model.generate(
                        inputs,
                        max_new_tokens=limit,
                        do_sample=False,
                        pad_token_id=tokenizer.eos_token_id,
                    )
                content = tokenizer.decode(output[0, inputs.shape[1] :], skip_special_tokens=True)
                self.send(
                    {
                        "message": {"role": "assistant", "content": content},
                        "done": True,
                        "done_reason": "stop"
                        if output[0, -1].item() == tokenizer.eos_token_id
                        else "length",
                    }
                )
            except Exception:
                self.send({"error": "inference_failed"}, 500)
            finally:
                lock.release()

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--adapter", type=Path, required=True)
    p.add_argument("--port", type=int, default=11435)
    a = p.parse_args()
    serve(json.loads(a.config.read_text(encoding="utf-8")), a.adapter, a.port)


if __name__ == "__main__":
    main()
