"""HTML report generator for Dependabot alert investigations.

Produces a self-contained HTML file styled like a code coverage report.
Each vulnerable code path is shown with source context and the target
line highlighted.
"""

from __future__ import annotations

import html


CONTEXT_LINES = 5


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
    vulnerable_paths = verdict.get("vulnerable_paths", [])

    # Redact sensitive details for affected alerts — the artifact is
    # world-readable on public repos.  The full analysis lives in the
    # private security advisory.
    if affected:
        reason = "Details redacted — see the security advisory for this alert."
        vulnerable_paths = []
    else:
        reason = verdict.get("reason", "(none)")

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
