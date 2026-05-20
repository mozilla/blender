"""Report generator for Dependabot alert investigations.

Produces markdown step summaries and annotations for GitHub Actions.
"""

from __future__ import annotations


def render_markdown(
    repo_name: str,
    alert_number: int,
    package: str,
    severity: str,
    action: str,
    verdict: dict,
) -> str:
    """Build a markdown summary for GitHub step summary."""
    affected = verdict.get("affected", False)
    confidence = verdict.get("confidence", "unknown")
    vulnerable_paths = verdict.get("vulnerable_paths", [])

    if affected:
        reason = "Details redacted — see the security advisory for this alert."
        vulnerable_paths = []
    else:
        reason = verdict.get("reason", "(none)")

    status_emoji = "\u274c" if affected else "\u2705"
    status_label = "AFFECTED" if affected else "NOT AFFECTED"

    action_labels = {
        "dismissed": "Alert dismissed",
        "noop": "No action taken",
        "private_fork": "Advisory created with private fork",
        "existing_pr": "Existing Dependabot PR found",
        "bump_pr_created": "Bump PR created",
        "npm_bump": "npm bump PR created",
    }
    action_text = action_labels.get(action, action)

    lines = [
        f"## {status_emoji} Alert #{alert_number} — {package}",
        "",
        f"**{status_label}** | {repo_name}",
        "",
        "| | |",
        "|---|---|",
        f"| **Severity** | {severity} |",
        f"| **Confidence** | {confidence} |",
        f"| **Action** | {action_text} |",
        f"| **Package** | {package} |",
        "",
        "### Analysis",
        "",
        reason,
    ]

    if vulnerable_paths:
        lines.append("")
        lines.append("### Vulnerable Code Paths")
        lines.append("")
        for vp in vulnerable_paths:
            lines.append(f"- `{vp}`")

    return "\n".join(lines) + "\n"


def annotation_line(
    alert_number: int,
    package: str,
    action: str,
    verdict: dict,
) -> str:
    """Build a one-line annotation message."""
    affected = verdict.get("affected", False)
    confidence = verdict.get("confidence", "unknown")

    action_labels = {
        "dismissed": "alert dismissed",
        "noop": "no action taken",
        "private_fork": "advisory created with private fork",
        "npm_bump": "npm bump PR created",
    }
    action_text = action_labels.get(action, action)

    status = "affected" if affected else "not affected"
    return f"Alert #{alert_number} ({package}): {status} ({confidence} confidence) — {action_text}"


def write_step_summary(
    repo_name: str,
    alert_number: int,
    package: str,
    severity: str,
    action: str,
    verdict: dict,
) -> None:
    """Write markdown summary to $GITHUB_STEP_SUMMARY and emit an annotation."""
    import os

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        md = render_markdown(
            repo_name, alert_number, package, severity, action, verdict
        )
        with open(summary_file, "a") as f:
            f.write(md)
        print("  Step summary written.")
    else:
        print("  $GITHUB_STEP_SUMMARY not set, skipping step summary.")

    notice = annotation_line(alert_number, package, action, verdict)
    print(f"::notice ::{notice}")
