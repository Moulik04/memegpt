"""The Groq model name is written down once, in config.py.

Render, Cloud Run (Terraform) and Kubernetes all run the same image, so a model
pinned in one of their config files can drift from the default the image was
tested with. Leaving the variables unset keeps a model swap to a one-line
change in config.py. These tests fail if a deploy file starts pinning a model
that differs from that default.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]

# env var name -> the Settings field whose default it overrides
MODEL_VARS = {
    "GROQ_MODEL": "groq_model",
    "MODERATION_MODEL": "moderation_model",
    "VISION_MODEL": "vision_model",
}

# One pattern per file format. Each captures (var name, pinned value).
_NAMES = "|".join(MODEL_VARS)
PIN_PATTERNS = {
    "render.yaml": re.compile(rf"key:\s*({_NAMES})\s*\n\s*value:\s*\"?([^\s\"]+)\"?"),
    "terraform/cloud_run.tf": re.compile(rf'name\s*=\s*"({_NAMES})"\s*\n\s*value\s*=\s*"([^"]+)"'),
    "k8s/configmap.yaml": re.compile(rf'^\s*({_NAMES}):\s*"?([^\s"]+)"?', re.MULTILINE),
}


def _pins(relative_path: str, text: str) -> dict[str, str]:
    return {name: value for name, value in PIN_PATTERNS[relative_path].findall(text)}


@pytest.mark.parametrize("relative_path", PIN_PATTERNS)
def test_deploy_files_do_not_pin_a_different_model(relative_path):
    defaults = Settings(_env_file=None)
    pins = _pins(relative_path, (REPO_ROOT / relative_path).read_text())
    for name, value in pins.items():
        default = getattr(defaults, MODEL_VARS[name])
        assert value == default, (
            f"{relative_path} pins {name}={value}, but config.py defaults to {default}. "
            "Remove the pin, or change the default in config.py instead."
        )


@pytest.mark.parametrize(
    "relative_path, sample",
    [
        ("render.yaml", "      - key: GROQ_MODEL\n        value: some/other-model\n"),
        ("terraform/cloud_run.tf", 'env {\n  name  = "GROQ_MODEL"\n  value = "some/other-model"\n}\n'),
        ("k8s/configmap.yaml", 'data:\n  GROQ_MODEL: "some/other-model"\n'),
    ],
)
def test_the_patterns_actually_detect_a_pin(relative_path, sample):
    """Guards against the check passing only because a regex stopped matching."""
    assert _pins(relative_path, sample) == {"GROQ_MODEL": "some/other-model"}
