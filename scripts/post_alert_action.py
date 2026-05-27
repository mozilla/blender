#!/usr/bin/env python3
"""Post-investigation action for Dependabot security alerts.

Reads .blender-alert-verdict.json and takes the appropriate action:

  unaffected + existing PR       -> comment on the PR, let other workflows handle
  unaffected + no PR             -> bump via lock tool or create PR
  unaffected + dismiss enabled   -> dismiss the alert (low/medium only)
  affected                       -> create advisory with private fork

Writes a summary to $GITHUB_STEP_SUMMARY and emits an annotation.

Environment variables:
  GH_TOKEN              -- GitHub token (required)
  REPO                  -- Target repo, e.g. mozilla/fx-private-relay (required)
  ALERT_NUMBER          -- Dependabot alert number (required)
  ALERT_PACKAGE         -- Package name (required)
  ALERT_ECOSYSTEM       -- Ecosystem, e.g. npm or pip (required)
  ALERT_SEVERITY        -- Alert severity (optional, for summary)
  ALERT_PATCHED_VERSION -- Version to bump to (optional)
  DRY_RUN               -- Set to "true" to skip mutations (default: false)
  DISMISS_UNAFFECTED    -- Set to "true" to dismiss unaffected alerts
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure the repo root is on sys.path so `scripts.alert_report` resolves
# when this file is invoked as `python /path/to/scripts/post_alert_action.py`.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from github import Auth, Github  # noqa: E402

from scripts.alert_report import write_step_summary  # noqa: E402

BLENDER_NAME = "BLEnder"
DISMISS_BLOCKED_SEVERITIES = {"critical", "high"}
VERDICT_FILE = ".blender-alert-verdict.json"
REQUIRED_KEYS = {
    "affected",
    "confidence",
    "reason",
    "vulnerable_paths",
    "recommended_action",
}


def load_verdict() -> dict | None:
    """Load and validate the alert verdict file."""
    if not os.path.exists(VERDICT_FILE):
        print(f"No verdict file at {VERDICT_FILE}.")
        return None

    with open(VERDICT_FILE) as f:
        verdict = json.load(f)

    missing = REQUIRED_KEYS - set(verdict.keys())
    if missing:
        print(f"Verdict missing keys: {missing}")
        return None

    return verdict


def create_advisory_and_fork(
    repo,
    alert_number: int,
    package_name: str,
    dry_run: bool,
    severity: str = "low",
) -> tuple[str, str]:
    """Create a security advisory with a private fork.

    Returns (advisory_ghsa_id, fork_full_name) on success.
    """
    summary = f"Dependency security update for {package_name}"
    description = (
        f"Automated security update for Dependabot alert #{alert_number}. "
        f"See the advisory for details."
    )

    if dry_run:
        print(f"  DRY_RUN: would create advisory: {summary}")
        return ("", "")

    # Create advisory via raw API (PyGithub has no built-in method)
    url = f"/repos/{repo.full_name}/security-advisories"
    payload = {
        "summary": summary,
        "description": description,
        "severity": severity or "low",
        "start_private_fork": True,
    }
    try:
        _, data = repo._requester.requestJsonAndCheck("POST", url, input=payload)
    except Exception as e:
        # Duplicate advisory returns 422
        error_str = str(e)
        if "422" in error_str or "already exists" in error_str.lower():
            print(f"  Advisory already exists for alert #{alert_number}, skipping.")
            return ("", "")
        raise

    ghsa_id = data.get("ghsa_id", "")
    print(f"  Created advisory {ghsa_id}")

    # Poll for private fork readiness (up to 5 minutes)
    fork_full_name = ""
    advisory_url = f"/repos/{repo.full_name}/security-advisories/{ghsa_id}"
    for attempt in range(10):
        time.sleep(min(30, 5 * (2**attempt)))
        _, advisory_data = repo._requester.requestJsonAndCheck("GET", advisory_url)
        forks = advisory_data.get("vulnerabilities", [])
        if forks:
            # The fork repo is in the advisory's fork field
            fork_info = advisory_data.get("private_fork", {})
            if fork_info:
                fork_full_name = fork_info.get("full_name", "")
                break
        # Also check top-level
        if advisory_data.get("private_fork"):
            fork_full_name = advisory_data["private_fork"].get("full_name", "")
            if fork_full_name:
                break

    if fork_full_name:
        print(f"  Private fork ready: {fork_full_name}")
    else:
        print("  Private fork not ready after polling. Remediate job may fail.")

    return (ghsa_id, fork_full_name)


def find_existing_bump_pr(
    repo,
    package_name: str,
) -> int | None:
    """Find an open PR that bumps this package.

    Checks for both Dependabot PRs and BLEnder bump PRs.
    Returns the PR number if found, None otherwise.
    """
    pulls = repo.get_pulls(state="open")
    package_lower = package_name.lower()
    for pr in pulls:
        title_lower = pr.title.lower()
        is_dependabot = pr.user.login == "dependabot[bot]"
        is_blender = pr.head.ref.startswith("blender/security-bump-")
        if (is_dependabot or is_blender) and package_lower in title_lower:
            print(f"  Found existing PR #{pr.number}: {pr.title}")
            return pr.number
    return None


def _run_url() -> str:
    """Build a link to the current GitHub Actions run, or empty string."""
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if server and repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return ""


def comment_on_pr(
    repo,
    pr_number: int,
    reason: str,
    dry_run: bool,
) -> None:
    """Comment on a PR with BLEnder's investigation results."""
    run_link = _run_url()
    investigated = f"[investigated]({run_link})" if run_link else "investigated"
    body = (
        f"**{BLENDER_NAME} {investigated}:** This dependency has an open "
        f"security alert, but the repo is **not affected**.\n\n> {reason}\n\n"
        "This PR can be reviewed and merged as a normal dependency update."
    )
    if dry_run:
        print(f"  DRY_RUN: would comment on PR #{pr_number}")
        return

    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(body)
    print(f"  Commented on PR #{pr_number}")


def find_dependency_pin(
    repo,
    package_name: str,
    ecosystem: str,
) -> tuple[str, str, str] | None:
    """Find the file and line that pins a dependency.

    Returns (file_path, old_content, new_line_pattern) or None if not found.
    Searches common dependency files for the package pin.
    """
    import re

    if ecosystem == "pip":
        candidates = [
            "requirements.txt",
            "requirements.in",
        ]
        # Also check requirements/*.txt
        try:
            contents = repo.get_contents("requirements")
            if isinstance(contents, list):
                for item in contents:
                    if item.name.endswith(".txt"):
                        candidates.append(item.path)
        except Exception:
            pass

        pin_pattern = re.compile(
            rf"^{re.escape(package_name)}\s*[=~><]=", re.IGNORECASE | re.MULTILINE
        )
        for path in candidates:
            try:
                file_content = repo.get_contents(path)
                text = file_content.decoded_content.decode("utf-8")
                if pin_pattern.search(text):
                    print(f"  Found {package_name} pin in {path}")
                    return (path, text, file_content.sha)
            except Exception:
                continue

        # Also check pyproject.toml [project.dependencies] and optional-deps
        try:
            file_content = repo.get_contents("pyproject.toml")
            text = file_content.decoded_content.decode("utf-8")
            if pin_pattern.search(text):
                print(f"  Found {package_name} pin in pyproject.toml")
                return ("pyproject.toml", text, file_content.sha)
        except Exception:
            pass

    elif ecosystem == "npm":
        try:
            file_content = repo.get_contents("package.json")
            text = file_content.decoded_content.decode("utf-8")
            if package_name.lower() in text.lower():
                print(f"  Found {package_name} in package.json")
                return ("package.json", text, file_content.sha)
        except Exception:
            pass

    return None


def create_bump_pr(
    repo,
    package_name: str,
    ecosystem: str,
    patched_version: str,
    alert_number: int,
    dry_run: bool,
) -> int | None:
    """Create a PR that bumps a dependency to the patched version.

    Returns the PR number on success, or None on failure.
    """
    import re

    if not patched_version:
        print("  No patched version available. Cannot create bump PR.")
        return None

    pin_info = find_dependency_pin(repo, package_name, ecosystem)
    if pin_info is None:
        print(f"  Cannot find {package_name} pin in repo. Cannot create bump PR.")
        return None

    file_path, old_text, file_sha = pin_info

    # Build the updated file content
    if ecosystem == "pip":
        # Replace version pins like: Django==5.2.13 or Django>=5.2.13
        new_text = re.sub(
            rf"(?im)^({re.escape(package_name)}\s*==\s*)\S+",
            rf"\g<1>{patched_version}",
            old_text,
        )
        if new_text == old_text:
            print(f"  Could not update version pin in {file_path}.")
            return None
    else:
        print(f"  Unsupported ecosystem: {ecosystem}")
        return None

    branch_name = f"blender/security-bump-{package_name.lower()}"
    pr_title = f"Bump {package_name} to {patched_version} (security)"
    run_link = _run_url()
    investigated = f"[investigated]({run_link})" if run_link else "investigated"
    pr_body = (
        f"## Summary\n\n"
        f"Bumps **{package_name}** to `{patched_version}` to resolve "
        f"[open security alerts]"
        f"(https://github.com/{repo.full_name}/security/dependabot"
        f"?q=is%3Aopen+{package_name}).\n\n"
        f"{BLENDER_NAME} {investigated} and determined the repo is "
        f"**not affected**, but bumping the dependency is good hygiene.\n\n"
        f"---\n"
        f"*Created by [{BLENDER_NAME}](https://github.com/mozilla/blender)*"
    )

    if dry_run:
        print(f"  DRY_RUN: would create bump PR: {pr_title}")
        print(f"  DRY_RUN: branch={branch_name}, file={file_path}")
        return 0

    try:
        # Create branch from default branch
        default_branch = repo.default_branch
        ref = repo.get_git_ref(f"heads/{default_branch}")
        sha = ref.object.sha

        # Check if branch already exists
        try:
            repo.get_git_ref(f"heads/{branch_name}")
            print(f"  Branch {branch_name} already exists. Skipping.")
            return None
        except Exception:
            pass  # Branch doesn't exist, good

        repo.create_git_ref(f"refs/heads/{branch_name}", sha)
        print(f"  Created branch {branch_name}")

        # Update the file
        repo.update_file(
            file_path,
            f"Bump {package_name} to {patched_version}\n\n"
            f"Resolves security alert #{alert_number}.",
            new_text,
            file_sha,
            branch=branch_name,
        )
        print(f"  Updated {file_path} on {branch_name}")

        # Open the PR
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base=default_branch,
        )
        print(f"  Created PR #{pr.number}: {pr.html_url}")
        return pr.number

    except Exception as e:
        print(f"  Failed to create bump PR: {e}")
        return None


def detect_pip_lock_tool(
    repo,
) -> tuple[str, str] | None:
    """Detect which pip lock tool the repo uses.

    Checks for lock files in order of preference and returns
    (tool_name, command_template) or None if no lock file found.
    """
    lock_files = {
        "uv.lock": ("uv", "uv lock --upgrade-package {pkg}"),
        "poetry.lock": ("poetry", "poetry update {pkg}"),
        "Pipfile.lock": ("pipenv", "pipenv update {pkg}"),
    }
    for lock_file, (tool, cmd) in lock_files.items():
        try:
            repo.get_contents(lock_file)
            print(f"  Found {lock_file} — using {tool}")
            return (tool, cmd)
        except Exception:
            continue
    return None


def dismiss_alert(
    repo,
    alert_number: int,
    reason: str,
    dry_run: bool,
) -> None:
    """Dismiss a Dependabot alert as not used (unaffected)."""
    if dry_run:
        print(f"  DRY_RUN: would dismiss alert #{alert_number}")
        return

    url = f"/repos/{repo.full_name}/dependabot/alerts/{alert_number}"
    payload = {
        "state": "dismissed",
        "dismissed_reason": "not_used",
        "dismissed_comment": f"{BLENDER_NAME}: {reason}",
    }
    repo._requester.requestJsonAndCheck("PATCH", url, input=payload)
    print(f"  Dismissed alert #{alert_number}")


def main() -> None:
    token = os.environ.get("GH_TOKEN", "")
    repo_name = os.environ.get("REPO", "")
    alert_number = int(os.environ.get("ALERT_NUMBER", "0"))
    package_name = os.environ.get("ALERT_PACKAGE", "unknown")
    ecosystem = os.environ.get("ALERT_ECOSYSTEM", "unknown")
    severity = os.environ.get("ALERT_SEVERITY", "unknown")
    patched_version = os.environ.get("ALERT_PATCHED_VERSION", "")
    dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
    dismiss_enabled = os.environ.get("DISMISS_UNAFFECTED", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    if not token or not repo_name:
        print("Error: GH_TOKEN and REPO are required.")
        sys.exit(1)

    if alert_number == 0:
        print("Error: ALERT_NUMBER is required.")
        sys.exit(1)

    g = Github(auth=Auth.Token(token))
    repo = g.get_repo(repo_name)

    verdict = load_verdict()
    if verdict is None:
        print("No valid verdict. Defaulting to no-op.")
        write_output("action", "noop")
        return

    affected = verdict.get("affected", False)
    recommended = verdict.get("recommended_action", "bump_pr")
    print(f"Verdict: affected={affected}, recommended={recommended}")
    print(f"  Reason: {verdict.get('reason', '(none)')}")

    reason = verdict.get("reason", "(none)")

    if not affected:
        # Check for an existing PR (Dependabot or BLEnder) that bumps this package
        existing_pr = find_existing_bump_pr(repo, package_name)

        if existing_pr:
            print(f"  Existing PR #{existing_pr} covers this package.")
            comment_on_pr(repo, existing_pr, reason, dry_run)
            action = "existing_pr"
        elif recommended == "bump_pr":
            if ecosystem == "npm" and patched_version:
                print("  npm ecosystem — deferring to npm_bump workflow step.")
                action = "npm_bump"
                write_output("npm_package", package_name)
                write_output("npm_version", patched_version)
                write_output("alert_number", str(alert_number))
            elif ecosystem == "npm":
                print("  npm ecosystem but no patched version. Cannot bump.")
                action = "noop"
            else:
                print("  No existing PR. Creating bump PR.")
                pr_num = create_bump_pr(
                    repo,
                    package_name,
                    ecosystem,
                    patched_version,
                    alert_number,
                    dry_run,
                )
                if pr_num is not None:
                    action = "bump_pr_created"
                    if pr_num > 0:
                        write_output("bump_pr_number", str(pr_num))
                else:
                    # No direct pin — try lock file upgrade
                    if ecosystem == "pip" and patched_version:
                        lock_tool = detect_pip_lock_tool(repo)
                        if lock_tool:
                            tool_name, _ = lock_tool
                            print(f"  Lock tool detected: {tool_name}")
                            action = "pip_lock_bump"
                            write_output("pip_package", package_name)
                            write_output("pip_version", patched_version)
                            write_output("pip_lock_tool", tool_name)
                            write_output("alert_number", str(alert_number))
                        else:
                            print("  No direct pin or lock tool. No action.")
                            action = "noop"
                    else:
                        action = "noop"
        elif dismiss_enabled and severity.lower() not in DISMISS_BLOCKED_SEVERITIES:
            print("  Unaffected + dismiss enabled. Dismissing alert.")
            dismiss_alert(repo, alert_number, reason, dry_run)
            action = "dismissed"
        elif dismiss_enabled:
            print(
                f"  Unaffected but severity is {severity}."
                " Recommend manual review before dismissing."
            )
            action = "noop"
        else:
            action = "noop"
        write_output("action", action)
    else:
        print("  Affected. Creating advisory and private fork.")
        ghsa_id, fork_repo = create_advisory_and_fork(
            repo,
            alert_number,
            package_name,
            dry_run,
            severity=severity.lower() if severity else "low",
        )
        action = "private_fork"
        write_output("action", action)
        write_output("advisory_ghsa_id", ghsa_id)
        write_output("fork_repo", fork_repo)

    write_step_summary(repo_name, alert_number, package_name, severity, action, verdict)


def write_output(key: str, value: str) -> None:
    """Write a key=value pair to $GITHUB_OUTPUT."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"  output: {key}={value}")


if __name__ == "__main__":
    main()
