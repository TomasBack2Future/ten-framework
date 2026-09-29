"""Validated session-start settings; secrets are referenced, never serialized."""

from dataclasses import dataclass, field
from copy import deepcopy

from .profiles import profile_for, validate_criteria

DEFAULTS = {
    "executor": {"enabled": False},
    "voice": {"prompt": "", "language": "en"},
    "compression": {
        "enabled": False,
        "prompt": "",
        "summary_prompt": "",
        "threshold": 0.7,
        "trigger_chars": 8000,
        "keep_turns": 3,
        "timeout_ms": 10000,
        "cooldown_ms": 30000,
        "max_summary_chars": 4000,
        "max_chars": 48000,
        "max_messages": 128,
    },
    "turn": {"enabled": True},
    "start": {"enabled": True, "prompt": "", "threshold": 0.6},
    "stop": {
        "enabled": True,
        "prompt": "",
        "threshold": 0.65,
        "max_wait_ms": 800,
    },
    "backchannel": {
        "enabled": False,
        "prompt": "",
        "threshold": 0.8,
        "phrases": ["Mm-hmm.", "I see."],
        "cooldown_ms": 5000,
        "valid_ms": 600,
    },
    "provider": {
        "name": "jev",
        "profile": "tuned",
        "sd_endpoint": "https://api.scaledown.xyz/v1/scaledown",
        "sd_compress_endpoint": "https://api.scaledown.xyz/compress/raw/",
        "sd_secret_env": "SCALEDOWN_API_KEY",
        "model": "jev-latest",
        "endpoint": "https://api.typesafe.ai/v1/systemone",
        "secret_env": "JEV_API_KEY",
        "timeout_ms": 800,
        "failure_policy": "bounded_wait",
    },
    "scheduling": {
        "merge_ms": 80,
        "min_interval_ms": 120,
        "max_wait_ms": 5000,
        "max_inflight": 1,
    },
    "wait": {
        "answer_ms": 250,
        "clarify_ms": 900,
        "continuation_ms": 1400,
        "explicit_wait_ms": 4000,
        "ignore_ms": 1800,
    },
    "observation": {
        "enabled": True,
        "include_text": False,
        "buffer_limit": 256,
    },
    "playback": {
        "stop_ack_timeout_ms": 500,
        "chars_per_second": 14,
        "context_responses": 12,
    },
    "transport": {"enabled": False, "mock_audio": False},
}


# Criteria are separately overridable; their labels remain a fixed contract.
for _kind in ("start", "stop", "backchannel", "compression"):
    DEFAULTS[_kind]["criteria"] = {}
DEFAULTS["start"]["score_mode"] = "legacy_reply"
DEFAULTS["route"] = {
    "prompt": "",
    "criteria": {},
    "threshold": 0.75,
    "task_control_threshold": 0.75,
}
DEFAULTS["support"] = {"prompt": "", "criteria": {}, "threshold": 0.75}


@dataclass
class Config:
    """Reject unknown options, incompatible limits and unsafe endpoints."""

    values: dict = field(default_factory=lambda: deepcopy(DEFAULTS))

    @classmethod
    def load(cls, raw=None):
        values = deepcopy(DEFAULTS)
        raw = raw or {}
        provider = raw.get("provider", {})
        if not isinstance(provider, dict):
            raise ValueError("invalid provider configuration")
        name = provider.get("name", values["provider"]["name"])
        profile = provider.get("profile", values["provider"]["profile"])
        if profile not in ("baseline", "tuned"):
            raise ValueError("unknown decision profile")
        if name not in ("jev", "sd", "sd_jev", "mock"):
            raise ValueError("unknown decision mode")
        if profile == "tuned":
            values["provider"]["model"] = "jev-1.13.0"
            for kind, spec in profile_for(name).items():
                values[kind].update(
                    prompt=spec["instructions"],
                    criteria=deepcopy(spec["criteria"]),
                    threshold=spec["threshold"],
                )
                if kind == "start":
                    values[kind]["score_mode"] = spec["score_mode"]
                if kind == "route":
                    values[kind]["threshold"] = spec["execute_threshold"]
                    values[kind]["task_control_threshold"] = spec[
                        "task_control_threshold"
                    ]
        for section, options in (raw or {}).items():
            if section not in values or not isinstance(options, dict):
                raise ValueError("unknown configuration section")
            for key, value in options.items():
                if key not in values[section]:
                    raise ValueError(f"unknown option: {section}.{key}")
                default = values[section][key]
                if isinstance(default, bool):
                    valid = isinstance(value, bool)
                elif isinstance(default, int):
                    valid = isinstance(value, int) and not isinstance(
                        value, bool
                    )
                elif isinstance(default, float):
                    valid = isinstance(value, (int, float)) and not isinstance(
                        value, bool
                    )
                else:
                    valid = isinstance(value, type(default))
                if not valid:
                    raise ValueError(f"invalid type: {section}.{key}")
                # Empty UI prompt overrides mean use the selected profile.
                if key == "prompt" and not value:
                    continue
                values[section][key] = deepcopy(value)
        localized_phrases = {
            "ja": ["うん。", "なるほど。"],
            "ko": ["네.", "그렇군요."],
        }
        if "phrases" not in raw.get("backchannel", {}):
            language = values["voice"]["language"]
            if language in localized_phrases:
                values["backchannel"]["phrases"] = localized_phrases[language]
        cfg = cls(values)
        cfg.validate()
        return cfg

    def __getitem__(self, key):
        return self.values[key]

    def validate(self):
        if self["voice"]["language"] not in ("en", "ja", "ko"):
            raise ValueError("invalid voice language")
        for section, options in self.values.items():
            for key, value in options.items():
                if key.endswith("_ms") and not 0 <= value <= 60000:
                    raise ValueError(f"out of range: {section}.{key}")
                if key.endswith("prompt") and len(value) > 4096:
                    raise ValueError("prompt exceeds 4096 characters")
                if key.endswith("threshold") and not 0 <= value <= 1:
                    raise ValueError("threshold outside [0,1]")
        if self["support"]["threshold"] <= 0:
            raise ValueError("support threshold must be positive")
        sched = self["scheduling"]
        if sched["max_inflight"] != 1:
            raise ValueError(
                "MVP supports exactly one in-flight provider request"
            )
        if not 100 <= sched["max_wait_ms"] <= 30000:
            raise ValueError("max_wait_ms outside [100,30000]")
        if (
            max(sched["merge_ms"], sched["min_interval_ms"])
            > sched["max_wait_ms"]
        ):
            raise ValueError("trigger interval exceeds max wait")
        if not 50 <= self["provider"]["timeout_ms"] <= 10000:
            raise ValueError("provider timeout outside [50,10000]")
        if self["provider"]["name"] not in ("mock", "jev", "sd", "sd_jev"):
            raise ValueError("invalid decision mode")
        if self["start"]["score_mode"] not in (
            "top",
            "answer_plus_clarify",
            "legacy_reply",
        ):
            raise ValueError("invalid start score mode")
        for kind in (
            "start",
            "stop",
            "backchannel",
            "compression",
            "route",
            "support",
        ):
            validate_criteria(kind, self[kind]["criteria"])
        if self["provider"]["failure_policy"] not in ("bounded_wait", "hold"):
            raise ValueError("invalid failure policy")
        for endpoint in ("endpoint", "sd_endpoint", "sd_compress_endpoint"):
            if not self["provider"][endpoint].startswith("https://"):
                raise ValueError("provider requires HTTPS")
        for option in ("secret_env", "sd_secret_env"):
            name = self["provider"][option]
            if not name or not name.replace("_", "").isalnum():
                raise ValueError(
                    "secret_env must be an environment variable name"
                )
        if not 16 <= self["observation"]["buffer_limit"] <= 4096:
            raise ValueError("buffer_limit outside [16,4096]")
        if not 1 <= self["playback"]["context_responses"] <= 64:
            raise ValueError("context_responses outside [1,64]")
        if not 1 <= self["playback"]["chars_per_second"] <= 50:
            raise ValueError("chars_per_second outside [1,50]")
        comp = self["compression"]
        if not 1000 <= comp["trigger_chars"] <= 24000:
            raise ValueError("trigger_chars outside [1000,24000]")
        if not 1 <= comp["keep_turns"] <= 12:
            raise ValueError("keep_turns outside [1,12]")
        if not 1000 <= comp["timeout_ms"] <= 30000:
            raise ValueError("compression timeout outside [1000,30000]")
        if not 500 <= comp["max_summary_chars"] <= 8000:
            raise ValueError("max_summary_chars outside [500,8000]")
        if not comp["trigger_chars"] + 16000 <= comp["max_chars"] <= 96000:
            raise ValueError("max_chars must reserve one 16000-character input")
        if not 32 <= comp["max_messages"] <= 256:
            raise ValueError("max_messages outside [32,256]")
        phrases = self["backchannel"]["phrases"]
        if not 1 <= len(phrases) <= 8 or any(
            not isinstance(p, str) or not 1 <= len(p) <= 40 for p in phrases
        ):
            raise ValueError(
                "backchannel requires 1-8 short phrases (1-40 characters)"
            )
