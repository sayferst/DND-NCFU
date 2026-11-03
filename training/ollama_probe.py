"""Local Faun preflight/measurements. No pull, installation or paid fallback."""

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

FAUN_MODEL = "hf.co/limloop/MN-12B-Faun-RP-RU-GGUF:Q4_K_M"
PROMPTS = (
    "Опиши по-русски попытку взлететь на обычной метле. "
    "Движок подтвердил: полёта нет, монеты и предметы не получены.",
    "Опиши итог: из одного лука получена незавершённая заготовка снасти. "
    "Лук больше не оружие. Не делай за героя следующий ход.",
    "Опиши итог: зарегистрированная рукавица подобрана и находится у героя. "
    "Не отрицай её существование.",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local inference cannot redirect to another address")


def request(path, body=None, *, timeout=180, port=11434):
    if port not in (11434, 11435) or not path.startswith("/api/"):
        raise ValueError("Only the two local inference ports and API paths are supported")
    raw = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}" + path, data=raw, headers={"Content-Type": "application/json"}
    )
    # Only fixed loopback. No proxy credentials or external hosts are contacted.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=timeout) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Local response exceeds limit")
    return json.loads(data)


def probe(*, model=FAUN_MODEL, measure=False, requester=request):
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "model": model,
        "status": "BLOCKED_PROVIDER",
        "measurements": [],
        "context_tokens": 2048,
        "training_steps": 0,
        "human_quality_review": "NOT_PERFORMED",
    }
    try:
        tags = requester("/api/tags")
        actual = next((r for r in tags.get("models", []) if r.get("name") == model), None)
        if actual is None:
            report["status"] = "BLOCKED_MODEL"
            return report
        report["installed_digest"] = actual.get("digest")
        report["installed_bytes"] = actual.get("size")
        report["status"] = "INSTALLED_NOT_BENCHMARKED"
        if measure:
            for prompt in PROMPTS:
                started = time.perf_counter()
                result = requester(
                    "/api/chat",
                    {
                        "model": model,
                        "stream": False,
                        "messages": [{"role": "user", "content": prompt}],
                        "options": {
                            "num_ctx": 2048,
                            "num_predict": 512,
                            "temperature": 0,
                            "seed": 37,
                        },
                    },
                )
                duration = result.get("eval_duration", 0) / 1e9
                report["measurements"].append(
                    {
                        "elapsed_seconds": time.perf_counter() - started,
                        "load_seconds": result.get("load_duration", 0) / 1e9,
                        "eval_tokens": result.get("eval_count"),
                        "tokens_per_second": result.get("eval_count", 0) / duration
                        if duration
                        else None,
                        "response": result.get("message", {}).get("content", ""),
                        "done": result.get("done"),
                        "done_reason": result.get("done_reason"),
                    }
                )
            report["status"] = "MEASURED_REQUIRES_HUMAN_REVIEW"
    except (OSError, ValueError, urllib.error.URLError) as error:
        report["error_category"] = type(error).__name__
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=FAUN_MODEL)
    parser.add_argument("--measure", action="store_true")
    args = parser.parse_args()
    result = probe(model=args.model, measure=args.measure)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": result["status"], "training_steps": 0}))


if __name__ == "__main__":
    main()
