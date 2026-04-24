#!/usr/bin/env python3
"""Merge BLEnder defaults with per-repo overrides.

Reads config/defaults.yml and the target repo's .blender/blender.yml,
deep-merges the override values on top of defaults, and
writes flattened key=value pairs to $GITHUB_OUTPUT.

Usage:
  python scripts/load-config.py --defaults config/defaults.yml --repo-config target/.blender/blender.yml

Output keys (written to $GITHUB_OUTPUT):
  automerge_allow_major
  automerge_min_compatibility_score
  automerge_check_advisories
  fix_dry_run
  fix_max_claude_turns
  fix_max_budget_usd
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base. Override wins for leaf values."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def flatten(d: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict to key=value with underscore separators."""
    out: dict[str, str] = {}
    for key, value in d.items():
        flat_key = f"{prefix}{key}" if not prefix else f"{prefix}_{key}"
        if isinstance(value, dict):
            out.update(flatten(value, flat_key))
        elif isinstance(value, bool):
            out[flat_key] = str(value).lower()
        else:
            out[flat_key] = str(value)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge BLEnder config")
    parser.add_argument("--defaults", required=True, help="Path to defaults.yml")
    parser.add_argument("--repo-config", required=True, help="Path to repo blender.yml")
    args = parser.parse_args()

    # Load defaults
    with open(args.defaults) as f:
        defaults = yaml.safe_load(f) or {}

    # Load repo config overrides
    # Supports both flat format and legacy "blender:" wrapper
    overrides = {}
    try:
        with open(args.repo_config) as f:
            repo_config = yaml.safe_load(f) or {}
        if "blender" in repo_config and isinstance(repo_config["blender"], dict):
            overrides = repo_config["blender"]
        else:
            overrides = repo_config
    except FileNotFoundError:
        print("No repo config found, using defaults only.", file=sys.stderr)

    merged = deep_merge(defaults, overrides)
    flat = flatten(merged)

    # Write to $GITHUB_OUTPUT if available, else stdout
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            for key, value in sorted(flat.items()):
                f.write(f"{key}={value}\n")
                print(f"  {key}={value}")
    else:
        for key, value in sorted(flat.items()):
            print(f"{key}={value}")


if __name__ == "__main__":
    main()
