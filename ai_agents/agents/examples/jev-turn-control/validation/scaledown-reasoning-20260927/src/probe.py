"""Stdlib khipaa paired probe; credentials exist only in stdin/process memory."""

import concurrent.futures
import hashlib
import http.client
import json
import math
import ssl
import sys
import threading
import time


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def reasoning_fields(value, path="$"):
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            location = path + "." + key
            if "reasoning" in key.lower():
                result.append(
                    {
                        "path": location,
                        "type": type(item).__name__,
                        "text_chars": (
                            len(item) if isinstance(item, str) else None
                        ),
                    }
                )
            result.extend(reasoning_fields(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(reasoning_fields(item, f"{path}[{index}]"))
    return result


class Probe:
    def __init__(self, keys, questions):
        self.keys = keys
        self.questions = questions
        self.context = ssl.create_default_context()
        self.local = threading.local()
        self.lock = threading.Lock()

    def request(self, provider, body, arm, regime):
        endpoints = {
            "jev": ("api.typesafe.ai", "/v1/systemone"),
            "sd": ("api.scaledown.xyz", "/v1/scaledown"),
            "compress": ("api.scaledown.xyz", "/compress/raw/"),
        }
        host, path = endpoints[provider]
        if not hasattr(self.local, "pool"):
            self.local.pool = {}
        pool_key = (arm, host, path)
        conn = self.local.pool.get(pool_key) if regime == "warm" else None
        reused = conn is not None and conn.sock is not None
        if conn is None:
            conn = http.client.HTTPSConnection(
                host, timeout=12, context=self.context
            )
            if regime == "warm":
                self.local.pool[pool_key] = conn
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "jev-sd-reasoning-khipaa/1",
        }
        headers.update(
            {"Authorization": "Bearer " + self.keys["jev"]}
            if provider == "jev"
            else {"x-api-key": self.keys["sd"]}
        )
        row = {
            "provider": provider,
            "request": body,
            "request_hash": digest({"provider": provider, "body": body}),
            "connection_reused": reused,
            "observed_at_unix": time.time(),
            "status": None,
            "error": None,
            "resolved_model": None,
        }
        started = time.perf_counter()
        try:
            conn.request(
                "POST", path, body=canonical(body).encode(), headers=headers
            )
            response = conn.getresponse()
            raw = response.read().decode("utf-8", errors="replace")
            for key in self.keys.values():
                raw = raw.replace(key, "[REDACTED]")
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
                row["reasoning_fields"] = reasoning_fields(data)
                if provider != "compress":
                    for kind, question in body["questions"].items():
                        answer = data["answers"][kind]
                        probabilities = answer["probabilities"]
                        if (
                            answer["choice"] not in question["criteria"]
                            or set(probabilities) != set(question["criteria"])
                            or any(
                                type(v) not in (int, float)
                                or not math.isfinite(v)
                                or not 0 <= v <= 1
                                for v in probabilities.values()
                            )
                            or abs(sum(probabilities.values()) - 1) > 0.02
                        ):
                            raise ValueError("invalid_distribution")
        except Exception as exc:
            row["error"] = type(exc).__name__
            conn.close()
            self.local.pool.pop(pool_key, None)
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if regime == "cold":
            conn.close()
        return row

    def run(self, job):
        case = job["case"]
        for order, arm in enumerate(job["arms"]):
            profile = (
                "jev"
                if job["lane"] == "controlled" or arm == "sd_reasoning_on"
                else arm
            )
            questions = {k: self.questions[profile][k] for k in case["gold"]}
            state = case["state"]
            stages = []
            error = None
            started = time.perf_counter()
            if arm == "sd_jev":
                body = {
                    "context": canonical(state),
                    "prompt": "Preserve every field, speaker attribution, negation, task status, user prefix, ASR flags and original size. Classify with these definitions: "
                    + canonical(questions),
                    "scaledown": {"rate": "auto"},
                }
                comp = self.request("compress", body, arm, job["regime"])
                stages.append(comp)
                response = comp.get("response", {})
                text = response.get("compressed_prompt")
                if text is None and isinstance(response.get("results"), dict):
                    text = response["results"].get("compressed_prompt")
                if comp["error"]:
                    error = comp["error"]
                elif not isinstance(text, str) or not text.strip():
                    error = "invalid_compressed_state"
                else:
                    state = {"compressed_state_text": text}
            if not error:
                if arm in ("sd", "sd_reasoning_on"):
                    body = {
                        "model": "classify-1",
                        "reasoning": arm == "sd_reasoning_on",
                        "state": {"text": canonical(state)},
                        "questions": questions,
                    }
                    row = self.request("sd", body, arm, job["regime"])
                else:
                    body = {
                        "model": "jev-1.13.0",
                        "state": state,
                        "questions": questions,
                    }
                    row = self.request("jev", body, arm, job["regime"])
                stages.append(row)
                error = row["error"]
            elapsed = (time.perf_counter() - started) * 1000
            result = {
                "job_id": job["id"],
                "case_id": case["id"],
                "family": case["family"],
                "cohort": case["cohort"],
                "scenario": case["scenario"],
                "regime": job["regime"],
                "lane": job["lane"],
                "repeat": job["repeat"],
                "arm": arm,
                "arm_order": order,
                "profile": profile,
                "questions_hash": digest(questions),
                "stages": stages,
                "latency_ms": round(elapsed, 3),
                "error": error,
                "over_800ms": elapsed > 800,
                "observed_at_unix": time.time(),
            }
            if not error:
                result["answers"] = stages[-1]["response"]["answers"]
            if job.get("collection_epoch"):
                result["collection_epoch"] = job["collection_epoch"]
            with self.lock:
                print(canonical(result), flush=True)


def main():
    payload = json.load(sys.stdin)
    runner = Probe(payload.pop("keys"), payload["questions"])
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=payload.get("concurrency", 2)
    ) as pool:
        list(pool.map(runner.run, payload["jobs"]))


if __name__ == "__main__":
    main()
