"""Frozen candidate questions and original baseline; no runtime network loading."""

from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).parent
BASELINE = json.loads(
    (ROOT / "baseline_questions.json").read_text(encoding="utf-8")
)
PROFILES = json.loads(
    (ROOT / "decision_profiles.json").read_text(encoding="utf-8")
)


def profile_for(mode):
    return deepcopy(PROFILES["jev" if mode == "mock" else mode])


def validate_criteria(kind, criteria):
    if not criteria:
        return
    if set(criteria) != set(BASELINE[kind]["criteria"]):
        raise ValueError("criteria must preserve decision labels")
    if any(
        not isinstance(value, str) or not 1 <= len(value) <= 2000
        for value in criteria.values()
    ):
        raise ValueError("criteria must contain bounded nonempty descriptions")


def question_for(config, kind):
    return {
        "type": "choice",
        "instructions": config[kind]["prompt"]
        or BASELINE[kind]["instructions"],
        "criteria": config[kind]["criteria"] or BASELINE[kind]["criteria"],
    }
