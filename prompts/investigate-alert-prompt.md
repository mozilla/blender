# BLEnder: Investigate Dependabot security alert

## Alert details

- **Package:** {{ALERT_PACKAGE}} ({{ALERT_ECOSYSTEM}})
- **Severity:** {{ALERT_SEVERITY}}
- **Summary:** {{ALERT_SUMMARY}}
- **Vulnerable range:** {{ALERT_VULNERABLE_RANGE}}
- **Patched version:** {{ALERT_PATCHED_VERSION}}
- **CWEs:** {{ALERT_CWES}}

## Advisory description

{{ALERT_DESCRIPTION}}

## Ecosystem audit output

```
{{AUDIT_OUTPUT}}
```

## Your task

Determine whether this vulnerability affects the target repo's code.
Many Dependabot alerts flag transitive dependencies or code paths the
repo never exercises. Your job is to distinguish real impact from noise.

### Step 1: Run the ecosystem audit tool

Run the appropriate audit command for structured data:
- npm: `npm audit --json 2>/dev/null || true`
- pip: `pip-audit --format=json 2>/dev/null || true`

This confirms whether the package is a direct or transitive dependency
and which versions are installed.

### Step 2: Search for usage

Search the codebase for imports, requires, and references to
`{{ALERT_PACKAGE}}`. Check:
- Source code imports and usage
- Configuration files
- Lock files (to confirm installed version)
- Test files

### Step 3: Trace vulnerable code paths

Read the advisory description. Identify the specific functions,
methods, or protocols that are vulnerable. Then check whether this
repo calls those functions or exposes those code paths.

### Step 4: Assess transitive exposure

If the package is a transitive dependency:
- Identify which direct dependency pulls it in
- Check whether the direct dependency exposes the vulnerable API
- A transitive dep used only at build time is not affected at runtime

### Step 5: Write your verdict

Write your verdict to `.blender-alert-verdict.json` using the Bash tool:

```bash
cat > .blender-alert-verdict.json << 'VERDICT_EOF'
{
  "affected": false,
  "confidence": "high",
  "reason": "Brief explanation of why the repo is or is not affected",
  "vulnerable_paths": [],
  "recommended_action": "bump_pr"
}
VERDICT_EOF
```

**Fields:**
- `affected`: true if the vulnerability impacts this repo's code
- `confidence`: "high", "medium", or "low"
- `reason`: one-paragraph explanation
- `vulnerable_paths`: list of `file:line` strings where vulnerable code is called (empty if not affected)
- `recommended_action`: one of:
  - `"existing_pr"` — a Dependabot PR already bumps this package
  - `"bump_pr"` — not affected, but open a PR to bump the dependency
  - `"private_fork"` — affected, needs a fix in a private security fork

**Confidence levels:**
- `high`: clear evidence the package is or is not used in vulnerable ways
- `medium`: package is used but the vulnerable code path is ambiguous
- `low`: cannot determine with confidence

## Rules

- Do NOT edit any tracked files. Read and analyze only.
- Do NOT run `git` commands.
- Write ONLY `.blender-alert-verdict.json` via Bash.
- Be conservative. When in doubt, mark as affected.
