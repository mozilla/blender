#!/usr/bin/env python3
"""Post-investigation action for Dependabot security alerts.

Reads .blender-alert-verdict.json and takes the appropriate action:

  unaffected + dismiss enabled  -> dismiss the alert via API
  unaffected + dismiss disabled -> no-op (suggest bumping the package)
  affected                      -> create advisory with private fork

Writes an HTML summary report to .blender-alert-summary.html for upload
as a workflow artifact (visible only to users with Actions access).

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

import html
import json
import os
import sys
import time

from github import Auth, Github

VERDICT_FILE = ".blender-alert-verdict.json"
SUMMARY_FILE = ".blender-alert-summary.html"
REQUIRED_KEYS = {
    "affected",
    "confidence",
    "reason",
    "vulnerable_paths",
    "recommended_action",
}

CONTEXT_LINES = 5


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
        "severity": "low",
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


def dismiss_alert(
    repo,
    alert_number: int,
    reason: str,
    dry_run: bool,
) -> None:
    """Dismiss a Dependabot alert as inaccurate (unaffected)."""
    if dry_run:
        print(f"  DRY_RUN: would dismiss alert #{alert_number}")
        return

    url = f"/repos/{repo.full_name}/dependabot/alerts/{alert_number}"
    payload = {
        "state": "dismissed",
        "dismissed_reason": "inaccurate",
        "dismissed_comment": f"BLEnder: {reason}",
    }
    repo._requester.requestJsonAndCheck("PATCH", url, input=payload)
    print(f"  Dismissed alert #{alert_number}")


def read_code_snippet(file_path: str, target_line: int) -> list[tuple[int, str, bool]]:
    """Read lines around target_line from file_path.

    Returns a list of (line_number, text, is_target) tuples.
    Returns an empty list if the file cannot be read.
    """
    try:
        with open(file_path) as f:
            all_lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    start = max(0, target_line - CONTEXT_LINES - 1)
    end = min(len(all_lines), target_line + CONTEXT_LINES)

    result = []
    for i in range(start, end):
        line_num = i + 1
        text = all_lines[i].rstrip("\n")
        result.append((line_num, text, line_num == target_line))
    return result


def render_html(
    repo_name: str,
    alert_number: int,
    package: str,
    severity: str,
    action: str,
    verdict: dict,
) -> str:
    """Build a self-contained HTML summary report."""
    affected = verdict.get("affected", False)
    confidence = verdict.get("confidence", "unknown")
    reason = verdict.get("reason", "(none)")
    vulnerable_paths = verdict.get("vulnerable_paths", [])

    status_label = "AFFECTED" if affected else "UNAFFECTED"
    status_color = "#dc3545" if affected else "#28a745"

    action_labels = {
        "dismissed": "Alert dismissed",
        "noop": "No action taken",
        "private_fork": "Advisory created with private fork",
    }
    action_text = action_labels.get(action, action)

    severity_colors = {
        "critical": "#dc3545",
        "high": "#fd7e14",
        "medium": "#ffc107",
        "low": "#28a745",
    }
    sev_color = severity_colors.get(severity.lower(), "#6c757d")

    confidence_colors = {
        "high": "#28a745",
        "medium": "#ffc107",
        "low": "#dc3545",
    }
    conf_color = confidence_colors.get(confidence.lower(), "#6c757d")

    # Build code snippets HTML
    snippets_html = ""
    if vulnerable_paths:
        for vp in vulnerable_paths:
            parts = vp.rsplit(":", 1)
            file_path = parts[0]
            target_line = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

            snippet_header = (
                f'<div class="snippet">'
                f'<div class="snippet-header">{html.escape(vp)}</div>'
            )

            if target_line == 0:
                snippets_html += (
                    f"{snippet_header}"
                    f'<div class="snippet-body">'
                    f'<span class="no-source">No line number specified</span>'
                    f"</div></div>"
                )
                continue

            lines = read_code_snippet(file_path, target_line)
            if not lines:
                snippets_html += (
                    f"{snippet_header}"
                    f'<div class="snippet-body">'
                    f'<span class="no-source">Source file not available</span>'
                    f"</div></div>"
                )
                continue

            code_lines = ""
            for line_num, text, is_target in lines:
                cls = ' class="target-line"' if is_target else ""
                escaped = html.escape(text) if text else "&nbsp;"
                code_lines += (
                    f"<tr{cls}>"
                    f'<td class="line-num">{line_num}</td>'
                    f'<td class="code">{escaped}</td>'
                    f"</tr>\n"
                )

            snippets_html += (
                f"{snippet_header}"
                f'<div class="snippet-body"><table class="code-table">'
                f"{code_lines}</table></div></div>"
            )
    else:
        snippets_html = (
            '<div class="no-paths">No vulnerable code paths identified.</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alert #{alert_number} — {html.escape(package)} — BLEnder Report</title>
<style>
  :root {{
    --bg: #1a1a2e;
    --surface: #16213e;
    --card: #0f3460;
    --text: #e0e0e0;
    --text-muted: #a0a0b0;
    --border: #2a2a4a;
    --code-bg: #0d1117;
    --target-bg: rgba(250, 200, 50, 0.12);
    --target-border: #e2b340;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
  }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
  }}
  .header h1 {{
    font-size: 1.4rem;
    font-weight: 600;
  }}
  .header h1 span {{ color: var(--text-muted); font-weight: 400; }}
  .branding {{
    font-size: 0.85rem;
    color: var(--text-muted);
    text-align: right;
  }}
  .status-banner {{
    padding: 1rem 1.5rem;
    border-radius: 8px;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 1.1rem;
    font-weight: 600;
    border: 1px solid;
  }}
  .badge {{
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #fff;
  }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }}
  .meta-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
  }}
  .meta-card .label {{
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 0.25rem;
  }}
  .meta-card .value {{ font-size: 1rem; font-weight: 500; }}
  .section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 1.5rem;
    overflow: hidden;
  }}
  .section-title {{
    padding: 0.75rem 1rem;
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    background: var(--card);
    border-bottom: 1px solid var(--border);
  }}
  .section-body {{ padding: 1rem; }}
  .reason {{ font-size: 0.95rem; line-height: 1.7; }}
  .snippet {{ margin-bottom: 1rem; }}
  .snippet:last-child {{ margin-bottom: 0; }}
  .snippet-header {{
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.8rem;
    padding: 0.5rem 0.75rem;
    background: var(--card);
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    color: var(--text-muted);
  }}
  .snippet-body {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 0 0 6px 6px;
    overflow-x: auto;
  }}
  .code-table {{
    width: 100%;
    border-collapse: collapse;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.82rem;
    line-height: 1.5;
  }}
  .code-table td {{ padding: 0 0.75rem; white-space: pre; }}
  .code-table .line-num {{
    width: 1%;
    text-align: right;
    color: #484860;
    user-select: none;
    padding-right: 1rem;
    border-right: 1px solid var(--border);
  }}
  .code-table .code {{ padding-left: 1rem; }}
  .target-line {{
    background: var(--target-bg);
    border-left: 3px solid var(--target-border);
  }}
  .target-line .line-num {{ color: var(--target-border); font-weight: 700; }}
  .no-paths, .no-source {{
    color: var(--text-muted);
    font-style: italic;
    padding: 0.5rem 0;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Alert #{alert_number} <span>— {html.escape(package)}</span></h1>
    <div class="branding">BLEnder Investigation Report<br>{html.escape(repo_name)}</div>
  </div>

  <div class="status-banner" style="background: {status_color}18; border-color: {status_color}60;">
    <span class="badge" style="background: {status_color};">{status_label}</span>
    {html.escape(action_text)}
  </div>

  <div class="meta-grid">
    <div class="meta-card">
      <div class="label">Severity</div>
      <div class="value"><span class="badge" style="background: {sev_color};">{html.escape(severity)}</span></div>
    </div>
    <div class="meta-card">
      <div class="label">Confidence</div>
      <div class="value"><span class="badge" style="background: {conf_color};">{html.escape(confidence)}</span></div>
    </div>
    <div class="meta-card">
      <div class="label">Action</div>
      <div class="value">{html.escape(action)}</div>
    </div>
    <div class="meta-card">
      <div class="label">Package</div>
      <div class="value">{html.escape(package)}</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Analysis</div>
    <div class="section-body">
      <p class="reason">{html.escape(reason)}</p>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Code Paths</div>
    <div class="section-body">
      {snippets_html}
    </div>
  </div>
</div>
</body>
</html>
"""


def write_summary(
    path: str,
    repo_name: str,
    alert_number: int,
    package: str,
    severity: str,
    action: str,
    verdict: dict,
) -> None:
    """Write an HTML summary report for upload as a workflow artifact."""
    report = render_html(repo_name, alert_number, package, severity, action, verdict)
    with open(path, "w") as f:
        f.write(report)
    print(f"  Summary written to {path}")


def main() -> None:
    token = os.environ.get("GH_TOKEN", "")
    repo_name = os.environ.get("REPO", "")
    alert_number = int(os.environ.get("ALERT_NUMBER", "0"))
    package_name = os.environ.get("ALERT_PACKAGE", "unknown")
    severity = os.environ.get("ALERT_SEVERITY", "unknown")
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
        if dismiss_enabled:
            print("  Unaffected + dismiss enabled. Dismissing alert.")
            dismiss_alert(repo, alert_number, reason, dry_run)
            action = "dismissed"
        else:
            print("  Unaffected + dismiss disabled. Consider bumping the package.")
            action = "noop"
        write_output("action", action)
    else:
        print("  Affected. Creating advisory and private fork.")
        ghsa_id, fork_repo = create_advisory_and_fork(
            repo,
            alert_number,
            package_name,
            dry_run,
        )
        action = "private_fork"
        write_output("action", action)
        write_output("advisory_ghsa_id", ghsa_id)
        write_output("fork_repo", fork_repo)

    write_summary(
        SUMMARY_FILE, repo_name, alert_number, package_name, severity, action, verdict
    )


def write_output(key: str, value: str) -> None:
    """Write a key=value pair to $GITHUB_OUTPUT."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    print(f"  output: {key}={value}")


if __name__ == "__main__":
    main()
