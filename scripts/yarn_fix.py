#!/usr/bin/env python3
"""BLEnder yarn fix (Berry v2+): bump a dependency and update yarn.lock only.

Writes fixed=true|false to $GITHUB_OUTPUT. Classic yarn v1 is not supported.

Environment variables:
  BUMP_PACKAGE  -- package name (required)
  BUMP_VERSION  -- patched version, used for a resolutions pin (optional)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# [parent[@range]/]package[@range], per yarnpkg-parsers resolution.pegjs.
_PARENT = r"(?:(?:@[^/@]+/)?[^/@]+(?:@[^/]+)?/)?"
_RANGE = r"(?:@[^/]+)?"
_PLAIN_VERSION = re.compile(r"(?:npm:)?[^:@/]*")
_NPM_MAJOR = re.compile(r"@npm:([0-9]+)")


def blocking_key(resolutions: dict, package: str) -> str | None:
    """Return an existing key that a plain pin for package would override."""
    pattern = re.compile(_PARENT + re.escape(package) + _RANGE)
    for key, value in resolutions.items():
        if key == package:
            if not _PLAIN_VERSION.fullmatch(str(value)):
                return key
        elif pattern.fullmatch(key):
            return key
    return None


def insert_pin(resolutions: dict, package: str, version: str) -> dict:
    """Return resolutions with the pin right after the largest smaller key."""
    if package in resolutions:
        return {**resolutions, package: version}
    keys = list(resolutions)
    smaller = [k for k in keys if k < package]
    index = keys.index(max(smaller)) + 1 if smaller else 0
    items = list(resolutions.items())
    items.insert(index, (package, version))
    return dict(items)


def pin_resolution(path: str, package: str, version: str) -> str | None:
    """Pin package in package.json resolutions. Return a reason if unsafe."""
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)

    resolutions = manifest.get("resolutions")
    if resolutions is None:
        resolutions = {}
    if not isinstance(resolutions, dict):
        return "resolutions is not an object."

    key = blocking_key(resolutions, package)
    if key:
        return f"Existing resolution {key!r} would be overridden."

    manifest["resolutions"] = insert_pin(resolutions, package, version)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return None


def _json_docs(text: str) -> list:
    """Return each JSON document in yarn's --json output."""
    decoder = json.JSONDecoder()
    docs = []
    pos = 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return docs
        doc, pos = decoder.raw_decode(text, pos)
        docs.append(doc)


def audit_state(returncode: int, output: str, package: str) -> str:
    """Return clean, flagged, or error (the audit run failed)."""
    if returncode == 0:
        return "clean"
    try:
        docs = _json_docs(output)
    except json.JSONDecodeError:
        return "error"
    if not docs or any(
        isinstance(doc, dict) and doc.get("type") == "error" for doc in docs
    ):
        return "error"
    for doc in docs:
        if isinstance(doc, dict) and doc.get("value") == package:
            return "flagged"
    return "clean"


def major_versions(output: str) -> set[str]:
    """Return the major versions in `yarn why <pkg> --json` output."""
    majors = set()
    try:
        docs = _json_docs(output)
    except json.JSONDecodeError:
        return majors
    for doc in docs:
        children = doc.get("children") if isinstance(doc, dict) else None
        for key in children or {}:
            match = _NPM_MAJOR.search(key)
            if match:
                majors.add(match.group(1))
    return majors


def _run(
    *cmd: str, capture: bool = False, quiet: bool = False
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.DEVNULL if capture or quiet else None,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(cmd, 127, "", "")


def _pkg_audit_state(package: str) -> str:
    result = _run(
        "yarn", "npm", "audit", "--all", "--recursive", "--json", capture=True
    )
    return audit_state(result.returncode, result.stdout, package)


def _out(fixed: bool) -> None:
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as f:
        f.write(f"fixed={'true' if fixed else 'false'}\n")


def fix(package: str, version: str) -> bool:
    if not os.path.isfile("yarn.lock"):
        print("::warning ::No yarn.lock — not a yarn repo; skipping.")
        return False

    _run("corepack", "enable", capture=True)

    result = _run("yarn", "--version", capture=True)
    yarn_ver = result.stdout.strip() if result.returncode == 0 else "0"
    print(f"Detected yarn {yarn_ver}")
    if yarn_ver == "0" or yarn_ver.startswith("1."):
        print(
            "::warning ::yarn classic (v1) is not supported yet (see #122); skipping."
        )
        return False

    _run("yarn", "why", package, quiet=True)

    # -R takes the package name only (a version/range is rejected).
    print(f"Running: yarn up -R {package} --mode=update-lockfile")
    if _run("yarn", "up", "-R", package, "--mode=update-lockfile").returncode != 0:
        print(f"::warning ::'yarn up -R {package}' failed; trying a resolution.")

    state = _pkg_audit_state(package)
    if state == "error":
        print(
            f"::warning ::yarn npm audit failed to run — cannot verify {package}; "
            "treating as unremediated."
        )
        return False

    # Out-of-range patch: fall back to a resolutions pin, single-major trees only (#122).
    if state == "flagged":
        why = _run("yarn", "why", package, "--json", capture=True)
        if not version or len(major_versions(why.stdout)) != 1:
            print(
                f"::warning ::{package} needs a resolution but has multiple major "
                "lines (or no patched version) — manual review needed (#122)."
            )
            return False
        print(
            f"In-range bump insufficient; pinning {package} to {version} via resolutions."
        )
        try:
            reason = pin_resolution("package.json", package, version)
        except (OSError, ValueError, AttributeError) as e:
            reason = str(e)
        if reason:
            print(reason, file=sys.stderr)
            print(
                f"::warning ::could not pin {package} safely — manual review needed (#122)."
            )
            return False
        if _run("yarn", "install", "--mode=update-lockfile").returncode != 0:
            print(
                f"::warning ::yarn install failed after pinning {package} — "
                "treating as unremediated."
            )
            return False

    if _pkg_audit_state(package) != "clean":
        print(
            f"::warning ::{package} not verified clear after remediation — "
            "manual review needed (#122)."
        )
        return False
    diff = _run("git", "diff", "--quiet", "yarn.lock", "package.json", capture=True)
    if diff.returncode == 0:
        print(f"::warning ::no changes produced for {package}; nothing to open.")
        return False

    print(f"{package} cleared in yarn npm audit.")
    return True


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    package = os.environ.get("BUMP_PACKAGE", "")
    if not package:
        sys.exit("BUMP_PACKAGE is required")
    _out(fix(package, os.environ.get("BUMP_VERSION", "")))


if __name__ == "__main__":
    main()
