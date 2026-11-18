"""Shared registry and revision handling. This module never reads credentials."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "recipes/registry.json"
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def registry():
    return json.loads(REGISTRY.read_text())["dependencies"]


def revision(value):
    if re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return value.lower(), "commit"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/+@-]*", value):
        raise ValueError("Use a full 40-character Git commit hash or a tag name")
    if subprocess.run(["git", "check-ref-format", "refs/tags/" + value], capture_output=True).returncode:
        raise ValueError("Invalid Git tag")
    return value, "tag"


def build_environment():
    env = dict(os.environ)
    for key in list(env):
        if (key in {"GH_TOKEN", "GITHUB_TOKEN", "RELEASE_TOKEN", "GIT_CONFIG_COUNT", "GIT_CURL_VERBOSE"}
                or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "GIT_TRACE"))):
            env.pop(key, None)
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_GLOBAL="/dev/null", DEPOT_TOOLS_UPDATE="0")
    return env


def destination(dependency, override="", current=None):
    current = current or os.environ.get("GITHUB_REPOSITORY", "")
    selected = override or registry()[dependency].get("release_repository") or current
    if not REPOSITORY_PATTERN.fullmatch(selected):
        raise ValueError("Set GITHUB_REPOSITORY or RELEASE_REPOSITORY to OWNER/REPOSITORY")
    return selected
