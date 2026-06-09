#!/usr/bin/env python3
"""BLEnder gather-context: fetch PR metadata + context, build prompt.

This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
It writes the final prompt to .blender-prompt for run-claude.sh.

Always gathers: PR metadata, diff, body, release notes, CI status,
failing checks + annotations + raw job logs. The prompt template
determines which placeholders to use.

Environment variables:
  PR_NUMBER       -- PR number (required)
  REPO            -- GitHub repo, e.g. mozilla/fx-private-relay (required)
  GH_TOKEN        -- GitHub token for API calls (required)
  PROMPT_TEMPLATE -- Path to prompt template file (required)
  DEP_NAME        -- Dependency name (optional, for template substitution)
  OLD_VERSION     -- Old version (optional, for template substitution)
  NEW_VERSION     -- New version (optional, for template substitution)
  INSTALL_FAILED  -- "true" if install step failed (optional)
  INSTALL_LOG_FILE -- Path to install log file (optional)
  CONTEXT_DIR     -- Output directory for context artifacts (default: .blender-context)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from scripts.sanitize import sanitize_for_prompt
except ImportError:
    from sanitize import sanitize_for_prompt  # type: ignore[no-redef]


# -- Lock file filtering ------------------------------------------------------

LOCK_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "Gemfile.lock",
    "composer.lock",
    "Cargo.lock",
    "go.sum",
}


def filter_lock_file_diff(diff: str) -> str:
    """Remove lock file hunks from a unified diff.

    Splits on ``diff --git`` boundaries, drops sections whose path
    matches a known lock file, and inserts a placeholder.
    """
    if not diff:
        return diff

    # Split on file boundaries, keeping the delimiter
    parts = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)

    filtered: list[str] = []
    omitted = False
    for part in parts:
        if not part.strip():
            continue
        # Extract the b/ path from "diff --git a/... b/..."
        m = re.match(r"diff --git a/.+ b/(.+)", part)
        if m:
            filename = m.group(1).split("/")[-1]
            if filename in LOCK_FILES:
                omitted = True
                continue
        filtered.append(part)

    result = "".join(filtered)
    if omitted:
        result += "\n[lock file changes omitted]\n"
    return result


# -- GitHub API helpers -------------------------------------------------------

MAX_LINES_PER_STEP = 200
MAX_LINES_TOTAL = 500


def gh_api(endpoint: str, headers: list[str] | None = None) -> str:
    """Call ``gh api`` and return stdout. Returns empty string on failure."""
    cmd = ["gh", "api", endpoint]
    if headers:
        for h in headers:
            cmd.extend(["-H", h])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout


# -- Data fetching ------------------------------------------------------------


def fetch_pr_metadata(repo: str, pr_number: str) -> dict:
    """Fetch PR JSON and extract key fields."""
    raw = gh_api(f"repos/{repo}/pulls/{pr_number}")
    if not raw:
        print(f"Error: could not fetch PR #{pr_number}", file=sys.stderr)
        sys.exit(1)
    pr = json.loads(raw)
    return {
        "title": pr["title"],
        "branch": pr["head"]["ref"],
        "sha": pr["head"]["sha"],
        "author": pr["user"]["login"],
        "body": pr.get("body") or "(no body)",
        "raw": pr,
    }


def fetch_check_runs(repo: str, sha: str) -> tuple[dict, dict]:
    """Fetch check runs and commit statuses for a SHA."""
    checks_raw = gh_api(f"repos/{repo}/commits/{sha}/check-runs")
    checks = json.loads(checks_raw) if checks_raw else {"check_runs": []}

    statuses_raw = gh_api(f"repos/{repo}/commits/{sha}/status")
    statuses = json.loads(statuses_raw) if statuses_raw else {"statuses": []}

    return checks, statuses


def fetch_pr_diff(repo: str, pr_number: str) -> str:
    """Fetch the PR diff."""
    diff = gh_api(
        f"repos/{repo}/pulls/{pr_number}",
        headers=["Accept: application/vnd.github.v3.diff"],
    )
    return diff or "(diff unavailable)"


def fetch_release_notes(pr_body: str) -> str:
    """Best-effort fetch of release notes from the dependency repo."""
    match = re.search(r"https://github\.com/([^/]+/[^\s/)]+)", pr_body)
    if not match:
        return "(release notes unavailable)"
    dep_repo = match.group(1)
    raw = gh_api(f"repos/{dep_repo}/releases")
    if not raw:
        return "(release notes unavailable)"
    releases = json.loads(raw)
    parts = []
    for rel in releases[:5]:
        parts.append(f"## {rel.get('tag_name', '')}\n{rel.get('body', '')}\n")
    return "\n".join(parts) if parts else "(release notes unavailable)"


# -- CI log parsing -----------------------------------------------------------


def parse_job_log(raw_log: str) -> str:
    """Extract failing step output from a GitHub Actions job log.

    Strips timestamps and group markers. Returns the last
    MAX_LINES_PER_STEP lines of each failing section, up to
    MAX_LINES_TOTAL total.
    """
    if not raw_log.strip():
        return ""

    # GitHub Actions logs start with a UTF-8 BOM — strip it.
    raw_log = raw_log.lstrip("\ufeff")

    # Split on group markers to get sections
    sections = re.split(r"^.*##\[group\]", raw_log, flags=re.MULTILINE)

    timestamp_re = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z ", re.MULTILINE)
    marker_re = re.compile(r"##\[(group|endgroup|section)\].*$", re.MULTILINE)

    failing_parts: list[str] = []
    total_lines = 0

    for section in sections:
        if "##[error]" not in section:
            continue

        # Strip timestamps
        cleaned = timestamp_re.sub("", section)
        # Strip group/endgroup/section markers (keep ##[error] for visibility)
        cleaned = marker_re.sub("", cleaned)
        # Remove blank lines from stripping
        lines = [line for line in cleaned.splitlines() if line.strip()]

        # Truncate to last N lines
        if len(lines) > MAX_LINES_PER_STEP:
            lines = lines[-MAX_LINES_PER_STEP:]

        if total_lines + len(lines) > MAX_LINES_TOTAL:
            remaining = MAX_LINES_TOTAL - total_lines
            if remaining > 0:
                lines = lines[-remaining:]
            else:
                break

        failing_parts.append("\n".join(lines))
        total_lines += len(lines)

    return "\n\n".join(failing_parts)


def fetch_ci_logs(repo: str, checks: dict, statuses: dict) -> tuple[str, bool]:
    """Fetch CI logs for failing checks. Returns (logs_text, has_circleci)."""
    # Build CI status summary
    ci_status_lines: list[str] = []
    for cr in checks.get("check_runs", []):
        conclusion = cr.get("conclusion") or cr.get("status", "unknown")
        ci_status_lines.append(f"{cr['name']}: {conclusion}")
    for s in statuses.get("statuses", []):
        ci_status_lines.append(f"{s['context']}: {s['state']}")

    # Find failing checks
    failing_run_names = [
        cr["name"]
        for cr in checks.get("check_runs", [])
        if cr.get("conclusion") == "failure"
    ]
    failing_status_names = [
        s["context"]
        for s in statuses.get("statuses", [])
        if s.get("state") == "failure"
    ]
    failing_names = failing_run_names + failing_status_names

    if not failing_names:
        print("No failing checks found.")
        return "", False

    print("Failing checks:")
    for name in failing_names:
        print(f"  - {name}")

    ci_logs = ""
    has_circleci = False

    for check_name in failing_names:
        # Find check_id for annotation + log fetch
        check_id = None
        for cr in checks.get("check_runs", []):
            if cr["name"] == check_name and cr.get("conclusion") == "failure":
                check_id = cr["id"]
                break

        # Fetch annotations
        annotations = ""
        if check_id:
            ann_raw = gh_api(f"repos/{repo}/check-runs/{check_id}/annotations")
            if ann_raw:
                try:
                    ann_list = json.loads(ann_raw)
                    ann_lines = []
                    for a in ann_list:
                        path = a.get("path", "")
                        line = a.get("start_line", "")
                        level = a.get("annotation_level", "")
                        msg = a.get("message", "")
                        ann_lines.append(f"  {path}:{line}: {level}: {msg}")
                    annotations = "\n".join(ann_lines)
                except (json.JSONDecodeError, KeyError):
                    pass

        # Fetch raw job log (GitHub Actions only)
        raw_log_output = ""
        if check_id:
            print(f"  Fetching job log for {check_name} (id={check_id})...")
            raw_log = gh_api(f"repos/{repo}/actions/jobs/{check_id}/logs")
            if raw_log:
                raw_log_output = parse_job_log(raw_log)

        # Check for CircleCI status
        target_url = ""
        for s in statuses.get("statuses", []):
            if s["context"] == check_name and s.get("state") == "failure":
                target_url = s.get("target_url", "")
                break

        ci_logs += f"\n\n### Check: {check_name}\n"

        if raw_log_output:
            ci_logs += f"Job log output:\n{raw_log_output}\n"
            if annotations:
                ci_logs += f"Annotations:\n{annotations}\n"
        elif annotations:
            ci_logs += f"Annotations:\n{annotations}\n"
        elif target_url and "circleci" in target_url:
            ci_logs += (
                f"CircleCI check: {check_name}\n"
                f"URL: {target_url}\n"
                "WARNING: BLEnder cannot fetch CircleCI log output. You must "
                "reproduce the failure locally using the commands in the fix "
                "prompt. If you cannot determine the root cause, say so — do "
                "not guess.\n"
            )
            print("  Warning: CircleCI failure — logs not available.")
            has_circleci = True
            github_output = os.environ.get("GITHUB_OUTPUT")
            if github_output:
                with open(github_output, "a") as f:
                    f.write("HAS_CIRCLECI_FAILURE=true\n")
        else:
            ci_logs += (
                "(No log output available. Run the check locally to see errors.)\n"
            )

    return ci_logs, has_circleci


# -- Prompt building ---------------------------------------------------------


def build_prompt(template: str, substitutions: dict[str, str]) -> str:
    """Replace ``{{PLACEHOLDER}}`` markers in the template.

    Any ``{{`` sequences in substitution *values* are neutralized to
    prevent accidental template expansion from API-fetched content.
    """
    result = template
    for key, value in substitutions.items():
        # Neutralize {{ in values to prevent nested expansion
        safe_value = value.replace("{{", "{ {")
        result = result.replace(f"{{{{{key}}}}}", safe_value)
    return result


# -- Main ---------------------------------------------------------------------


def main() -> None:
    """Orchestrate context gathering and prompt building."""
    pr_number = os.environ.get("PR_NUMBER", "")
    repo = os.environ.get("REPO", "")
    gh_token = os.environ.get("GH_TOKEN", "")
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE", "")

    # Validate required env vars
    if not pr_number or not repo:
        print("Error: PR_NUMBER and REPO are required.", file=sys.stderr)
        sys.exit(1)
    if not pr_number.isdigit():
        print(
            f"Error: PR_NUMBER must be a positive integer, got: {pr_number}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not gh_token:
        print("Error: GH_TOKEN is required.", file=sys.stderr)
        sys.exit(1)
    if not prompt_template_path:
        print("Error: PROMPT_TEMPLATE is required.", file=sys.stderr)
        sys.exit(1)

    template_path = Path(prompt_template_path)
    if not template_path.is_file():
        print(
            f"Error: Prompt template not found: {prompt_template_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"BLEnder gather-context: PR #{pr_number} repo={repo}")

    # Fetch PR metadata
    print("Fetching PR metadata...")
    pr = fetch_pr_metadata(repo, pr_number)
    if pr["author"] != "dependabot[bot]":
        print(
            f"Error: PR #{pr_number} is authored by '{pr['author']}', "
            "not dependabot[bot]. Refusing to process.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  Title: {pr['title']}")
    print(f"  Branch: {pr['branch']}")
    print(f"  SHA: {pr['sha']}")

    # Fetch PR diff
    print("Fetching PR diff...")
    pr_diff = fetch_pr_diff(repo, pr_number)
    pr_diff_filtered = filter_lock_file_diff(pr_diff)

    # Fetch release notes
    print("Fetching release notes...")
    release_notes = fetch_release_notes(pr["body"])

    # Fetch CI status and logs
    print("Fetching CI status...")
    checks, statuses_json = fetch_check_runs(repo, pr["sha"])

    # Build CI status summary
    ci_status_lines: list[str] = []
    for cr in checks.get("check_runs", []):
        conclusion = cr.get("conclusion") or cr.get("status", "unknown")
        ci_status_lines.append(f"{cr['name']}: {conclusion}")
    for s in statuses_json.get("statuses", []):
        ci_status_lines.append(f"{s['context']}: {s['state']}")
    ci_status = "\n".join(ci_status_lines) if ci_status_lines else "No CI checks found."

    # Failing checks
    failing_run_names = [
        cr["name"]
        for cr in checks.get("check_runs", [])
        if cr.get("conclusion") == "failure"
    ]
    failing_status_names = [
        s["context"]
        for s in statuses_json.get("statuses", [])
        if s.get("state") == "failure"
    ]
    failing_checks = "\n".join(failing_run_names + failing_status_names)

    print("Fetching failing checks...")
    ci_logs, _has_circleci = fetch_ci_logs(repo, checks, statuses_json)

    # Sanitize all untrusted content
    safe_title = sanitize_for_prompt(pr["title"])
    safe_checks = sanitize_for_prompt(failing_checks)
    safe_logs = sanitize_for_prompt(ci_logs)
    safe_diff = sanitize_for_prompt(pr_diff_filtered)
    safe_body = sanitize_for_prompt(pr["body"])
    safe_notes = sanitize_for_prompt(release_notes)
    safe_ci = sanitize_for_prompt(ci_status)

    # Build prompt
    print(f"Building prompt from {prompt_template_path}...")
    template = template_path.read_text()

    substitutions = {
        "PR_TITLE": safe_title,
        "FAILING_CHECKS": safe_checks,
        "CI_LOGS": safe_logs,
        "PR_DIFF": safe_diff,
        "PR_BODY": safe_body,
        "RELEASE_NOTES": safe_notes,
        "CI_STATUS": safe_ci,
        "DEP_NAME": os.environ.get("DEP_NAME", ""),
        "OLD_VERSION": os.environ.get("OLD_VERSION", ""),
        "NEW_VERSION": os.environ.get("NEW_VERSION", ""),
    }

    # Install error placeholder
    install_error = ""
    if os.environ.get("INSTALL_FAILED") == "true" and os.environ.get(
        "INSTALL_LOG_FILE"
    ):
        log_path = Path(os.environ["INSTALL_LOG_FILE"])
        if log_path.is_file():
            print("Install failed — injecting last 200 lines of log into prompt.")
            lines = log_path.read_text().splitlines()
            raw_log = "\n".join(lines[-200:])
            install_error = sanitize_for_prompt(raw_log)
    substitutions["INSTALL_ERROR"] = install_error

    prompt = build_prompt(template, substitutions)

    # Write prompt
    Path(".blender-prompt").write_text(prompt)
    print("Prompt written to .blender-prompt")

    # Save context artifacts
    context_dir = Path(os.environ.get("CONTEXT_DIR", ".blender-context"))
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "pr-diff.txt").write_text(safe_diff)
    (context_dir / "pr-body.md").write_text(safe_body)
    (context_dir / "release-notes.md").write_text(safe_notes)
    (context_dir / "ci-status.txt").write_text(safe_ci)
    (context_dir / "failing-checks.txt").write_text(safe_checks)
    (context_dir / "ci-logs.txt").write_text(safe_logs)

    import shutil

    shutil.copy2(prompt_template_path, context_dir / "prompt-template.md")
    shutil.copy2(".blender-prompt", context_dir / "prompt-final.md")
    print(f"Context saved to {context_dir}/")


if __name__ == "__main__":
    main()
