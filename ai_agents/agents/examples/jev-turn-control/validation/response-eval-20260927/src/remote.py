"""Paired real provider collector. Stdin credentials stay in process memory."""

import concurrent.futures
import hashlib
import http.client
import json
import math
import ssl
import sys
import threading
import time
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Collector:
    def __init__(self, keys):
        self.keys = keys
        self.local = threading.local()
        self.lock = threading.Lock()
        self.cache = {}
        self.keylocks = {}
        self.path = Path("/work/provider-cache.jsonl")
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.cache[row["cache_key"]] = row

    def emit(self, row):
        with self.lock:
            print(canonical(row), flush=True)

    def request(self, provider, state, questions, repeat=0):
        key = digest([provider, state, questions, repeat])
        with self.lock:
            guard = self.keylocks.setdefault(key, threading.Lock())
        with guard:
            return self._request(provider, state, questions, repeat)

    def _request(self, provider, state, questions, repeat=0):
        body = {
            "model": "jev-1.13.0" if provider == "jev" else "classify-1",
            "state": state if provider == "jev" else {"text": canonical(state)},
            "questions": questions,
        }
        request_hash = digest({"provider": provider, "body": body})
        key = digest({"request_hash": request_hash, "repeat": repeat})
        with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        if not hasattr(self.local, "connections"):
            self.local.connections = {}
        host, path = (
            ("api.typesafe.ai", "/v1/systemone")
            if provider == "jev"
            else ("api.scaledown.xyz", "/v1/scaledown")
        )
        connection = self.local.connections.get(provider)
        if connection is None:
            connection = http.client.HTTPSConnection(
                host, timeout=12, context=ssl.create_default_context()
            )
            self.local.connections[provider] = connection
        row = {
            "record_type": "http",
            "cache_key": key,
            "request_hash": request_hash,
            "provider": provider,
            "repeat": repeat,
            "request": body,
            "prompt_hash": digest(questions),
            "observed_at_unix": time.time(),
            "connection_reused": connection.sock is not None,
            "resolved_model": None,
            "status": None,
            "error": None,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "jev-response-eval/2",
        }
        headers.update(
            {"Authorization": "Bearer " + self.keys["jev"]}
            if provider == "jev"
            else {"x-api-key": self.keys["scaledown"]}
        )
        started = time.perf_counter()
        try:
            connection.request(
                "POST", path, body=canonical(body).encode(), headers=headers
            )
            response = connection.getresponse()
            raw = response.read().decode("utf-8", errors="replace")
            for value in self.keys.values():
                raw = raw.replace(value, "[REDACTED]")
            row.update(
                status=response.status,
                response_raw=raw,
                response_headers={
                    k: v
                    for k, v in response.getheaders()
                    if k.lower()
                    in ("date", "x-request-id", "request-id", "server-timing")
                },
            )
            if response.status != 200:
                row["error"] = "HTTP_" + str(response.status)
            else:
                data = json.loads(raw)
                row["response"] = data
                row["resolved_model"] = data.get("model")
                for kind, question in questions.items():
                    answer = data["answers"][kind]
                    probs = answer["probabilities"]
                    if (
                        answer["choice"] not in question["criteria"]
                        or set(probs) != set(question["criteria"])
                        or any(
                            not isinstance(v, (int, float))
                            or not math.isfinite(v)
                            or not 0 <= v <= 1
                            for v in probs.values()
                        )
                        or abs(sum(probs.values()) - 1) > 0.02
                    ):
                        raise ValueError("invalid_distribution")
        except Exception as exc:
            row["error"] = type(exc).__name__
            connection.close()
            self.local.connections.pop(provider, None)
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        row["runtime_timeout_800ms"] = row["latency_ms"] > 800
        with self.lock:
            self.cache[key] = row
            with self.path.open("a", encoding="utf-8") as out:
                out.write(canonical(row) + "\n")
            print(canonical(row), flush=True)
        return row

    def paired(self, job):
        providers = ["jev", "scaledown"]
        if int(digest(job["id"])[-1], 16) % 2:
            providers.reverse()
        refs = {}
        for provider in providers:
            row = self.request(
                provider, job["state"], job["questions"], job.get("repeat", 0)
            )
            refs[provider] = row["cache_key"]
        self.emit(
            {
                "record_type": "pair",
                "job": {
                    k: v
                    for k, v in job.items()
                    if k not in ("state", "questions")
                },
                "refs": refs,
            }
        )


def main():
    payload = json.load(sys.stdin)
    collector = Collector(payload.pop("keys"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(collector.paired, payload["jobs"]))


if __name__ == "__main__":
    main()
