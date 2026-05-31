"""Shared config utilities for BLEnder scripts."""

from __future__ import annotations

import pathlib

import yaml


DEFAULTS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "config" / "defaults.yml"
)


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base. Override wins for leaf values."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_repo_config(repo) -> dict:
    """Load and merge config from a GitHub repo.

    Fetches .blender/blender.yml via the API, deep-merges it with
    the BLEnder defaults, and returns the merged config dict.

    Returns defaults only if the repo config is missing or unreadable.
    """
    with open(DEFAULTS_PATH) as f:
        defaults = yaml.safe_load(f) or {}

    try:
        content = repo.get_contents(".blender/blender.yml")
        repo_config = yaml.safe_load(content.decoded_content) or {}
        # Support legacy "blender:" wrapper
        if "blender" in repo_config and isinstance(repo_config["blender"], dict):
            repo_config = repo_config["blender"]
    except Exception:
        repo_config = {}

    return deep_merge(defaults, repo_config)
