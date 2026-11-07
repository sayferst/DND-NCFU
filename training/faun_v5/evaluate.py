"""Collect comparable responses from a user-started local OpenAI-compatible server.

No automatic model switching, remote requests, training or invented subjective grades.
"""

import argparse
import csv
import ipaddress
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from training.faun_v5.validate import sha


def local_endpoint(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise ValueError("Expected local HTTP API without URL credentials")
    host = parsed.hostname
    if host != "localhost" and not (host and ipaddress.ip_address(host).is_loopback):
        raise ValueError("Only loopback API endpoints are supported")
    if parsed.query or parsed.fragment:
        raise ValueError("Unexpected endpoint query or fragment")
    return url.rstrip("/") + "/chat/completions"


def cases(root, suite):
    root = Path(root)
    if suite == "regression":
        with (root / "regression_suite.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                yield {
                    "id": row["id"],
                    "messages": [{"role": "user", "content": row["prompt"]}],
                    "reference": row["expected"],
                }
    else:
        with (root / ("ood_eval_gold.jsonl" if suite == "ood" else "eval_gold.jsonl")).open(
            encoding="utf-8"
        ) as stream:
            yield from map(json.loads, stream)


def collect(root, endpoint, model, variant, suite, output, *, max_tokens=160, limit=0):
    endpoint = local_endpoint(endpoint)
    output = Path(output)
    if output.exists():
        raise ValueError("Use a new result file")
    params = {"temperature": 0, "seed": 42, "max_tokens": max_tokens, "stream": False}
    results = []
    for i, case in enumerate(cases(root, suite)):
        if limit and i >= limit:
            break
        payload = {**params, "model": model, "messages": case["messages"]}
        started = time.monotonic()
        record = {"id": case["id"], "reference": case["reference"], "human_grade": None}
        try:
            request = Request(
                endpoint,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=600) as reply:
                raw = reply.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Oversized response")
            body = json.loads(raw)
            choice = body["choices"][0]
            record.update(
                answer=choice["message"]["content"],
                finish_reason=choice.get("finish_reason"),
                usage=body.get("usage"),
                server_model=body.get("model"),
                truncated=choice.get("finish_reason") == "length",
                error=None,
            )
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError) as exc:
            record.update(error=type(exc).__name__, answer=None, finish_reason=None)
        record["seconds"] = round(time.monotonic() - started, 3)
        results.append(record)
        # Persist partial results after each response, including errors.
        report = {
            "status": "COLLECTED_REQUIRES_HUMAN_REVIEW",
            "variant": variant,
            "suite": suite,
            "parameters": params,
            "results": results,
            "manifest_sha256": sha(Path(root) / "manifest.json"),
            "training_steps": 0,
        }
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def compare(paths):
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    if len({r["variant"] for r in reports}) != len(reports):
        raise ValueError("Repeated variant")

    def contract(r):
        return (
            r["suite"],
            r["parameters"],
            r["manifest_sha256"],
            [x["id"] for x in r["results"]],
        )

    if any(contract(r) != contract(reports[0]) for r in reports[1:]):
        raise ValueError("Evaluation parameters, corpus or cases differ")
    return {
        "comparable_collection_contract": True,
        "variants": [
            {
                "variant": r["variant"],
                "cases": len(r["results"]),
                "errors": sum(x.get("error") is not None for x in r["results"]),
                "truncated": sum(x.get("truncated", False) for x in r["results"]),
                "graded": sum(x["human_grade"] is not None for x in r["results"]),
            }
            for r in reports
        ],
        "model_identity_requires_external_weight_hashes": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, default=Path("."))
    p.add_argument("--endpoint", default="http://127.0.0.1:8080/v1")
    p.add_argument("--model")
    p.add_argument("--variant", choices=("original", "lora_v1", "lora_v5"))
    p.add_argument("--suite", choices=("regression", "test", "ood"), default="regression")
    p.add_argument("--max-tokens", type=int, default=160)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--output", type=Path)
    p.add_argument("--compare", type=Path, nargs="+")
    a = p.parse_args()
    if a.compare:
        print(json.dumps(compare(a.compare), ensure_ascii=False, indent=2))
    else:
        if not a.model or not a.variant or not a.output or a.max_tokens < 1 or a.limit < 0:
            p.error("Supply model, variant, new output and valid limits")
        collect(
            a.dataset,
            a.endpoint,
            a.model,
            a.variant,
            a.suite,
            a.output,
            max_tokens=a.max_tokens,
            limit=a.limit,
        )


if __name__ == "__main__":
    main()
