"""One bounded decision contract for Jev, ScaleDown and compression → Jev."""

import asyncio
import json
import os

import aiohttp

from .profiles import BASELINE, question_for

CRITERIA = {kind: spec["criteria"] for kind, spec in BASELINE.items()}
PROMPTS = {kind: spec["instructions"] for kind, spec in BASELINE.items()}


def mock_answers(request):
    """Deterministic demo behavior; never labeled as a model probability."""
    text = request["state"].get("input_text", "").lower()
    if any(word in text for word in ("wait", "hold on", "等一下")):
        label = "explicit_wait"
    elif text.endswith(("?", "？", ".", "。")):
        label = "answer"
    elif text in ("um", "uh", "嗯"):
        label = "ignore"
    else:
        label = "continuation"
    labels = {
        "route": "conversation",
        "support": "unsupported",
        "compression": "compress",
        "start": label,
        "stop": (
            "continue"
            if text.strip(".! ") in ("yes", "yeah", "okay", "mm-hmm")
            else "stop"
        ),
        "backchannel": "backchannel" if label == "continuation" else "silent",
    }
    return {
        kind: {
            "label": labels[kind],
            "score": 1.0,
            "probabilities": {
                choice: float(choice == labels[kind])
                for choice in CRITERIA[kind]
            },
        }
        for kind in request["kinds"]
    }


class DecisionProvider:
    """Reuse HTTPS connections; a timeout covers both stages of sd_jev."""

    def __init__(self, config):
        self.config = config
        self.client = None

    async def decide(self, request):
        if self.config["provider"]["name"] == "mock":
            await asyncio.sleep(0)
            return mock_answers(request)
        try:
            return await asyncio.wait_for(
                self._decide(request),
                self.config["provider"]["timeout_ms"] / 1000,
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid provider response") from exc

    async def _post(self, endpoint, body, secret_env, header):
        key = os.environ.get(secret_env, "")
        if not key:
            raise ValueError("provider credential unavailable")
        if self.client is None:
            self.client = aiohttp.ClientSession()
        value = f"Bearer {key}" if header == "Authorization" else key
        async with self.client.post(
            endpoint, json=body, headers={header: value}, allow_redirects=False
        ) as response:
            if response.status != 200:
                raise ValueError(f"provider HTTP {response.status}")
            return await response.json()

    async def _decide(self, request):
        cfg = self.config["provider"]
        mode = cfg["name"]
        questions = {
            kind: question_for(self.config, kind) for kind in request["kinds"]
        }
        state = request["state"]
        if mode == "sd_jev":
            compressed = await self._post(
                cfg["sd_compress_endpoint"],
                {
                    "context": canonical_json(state),
                    "prompt": "Preserve every field, speaker attribution, negation, task status, user prefix, ASR flags and original size. Classify with these definitions: "
                    + canonical_json(questions),
                    "scaledown": {"rate": "auto"},
                },
                cfg["sd_secret_env"],
                "x-api-key",
            )
            text = compressed.get("compressed_prompt")
            if text is None and isinstance(compressed.get("results"), dict):
                text = compressed["results"].get("compressed_prompt")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("invalid compressed state")
            state = {"compressed_state_text": text}
        if mode == "sd":
            data = await self._post(
                cfg["sd_endpoint"],
                {
                    "model": "classify-1",
                    "state": {"text": canonical_json(state)},
                    "questions": questions,
                },
                cfg["sd_secret_env"],
                "x-api-key",
            )
        else:
            data = await self._post(
                cfg["endpoint"],
                {"model": cfg["model"], "state": state, "questions": questions},
                cfg["secret_env"],
                "Authorization",
            )
        result = {}
        for kind, question in questions.items():
            answer = data["answers"][kind]
            label, probabilities = answer["choice"], answer["probabilities"]
            if label not in question["criteria"] or set(probabilities) != set(
                question["criteria"]
            ):
                raise ValueError("invalid provider labels")
            if any(
                type(v) not in (int, float) or not 0 <= v <= 1
                for v in probabilities.values()
            ):
                raise ValueError("invalid provider probabilities")
            if abs(sum(probabilities.values()) - 1) > 0.02:
                raise ValueError("invalid probability distribution")
            result[kind] = {
                "label": label,
                "score": probabilities[label],
                "probabilities": probabilities,
            }
        return result

    async def route(self, state):
        """Intent/support gate only; never authorizes or executes a tool itself.

        A host must also check capabilities, required arguments, session ownership
        and explicit task targets. Provider errors propagate, never become execute.
        """
        visible = {
            key: state.get(key, default)
            for key, default in (
                ("text", ""),
                ("history", []),
                ("active_tasks", []),
                ("capabilities", []),
                ("stable", True),
            )
        }
        answers = await self.decide(
            {"state": visible, "kinds": ["route", "support"]}
        )
        route, support = answers["route"], answers["support"]
        label = route["label"]
        threshold = self.config["route"][
            "task_control_threshold" if label == "task_control" else "threshold"
        ]
        if label in ("execute", "task_control") and (
            not visible["stable"] or route["score"] < threshold
        ):
            label = "wait"
        support_label = support["label"]
        if support["score"] < self.config["support"]["threshold"]:
            support_label = "wait"
        return {
            "route": label,
            "raw_route": route["label"],
            "support": support_label,
            "probabilities": route["probabilities"],
            "support_probabilities": support["probabilities"],
            "provider": self.config["provider"]["name"],
            "profile": self.config["provider"]["profile"],
        }

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
