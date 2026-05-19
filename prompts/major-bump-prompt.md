# BLEnder: Evaluate major version bump

**{{DEP_NAME}}** from `{{OLD_VERSION}}` to `{{NEW_VERSION}}`

## PR diff

```
{{PR_DIFF}}
```

## PR body (changelog)

{{PR_BODY}}

## Release notes

{{RELEASE_NOTES}}

## CI status

{{CI_STATUS}}

## Your task

Evaluate whether this major version bump is safe to auto-merge without code changes.

### Step 1: Find all usage of `{{DEP_NAME}}`

Search the codebase for imports, requires, API calls, and configuration referencing this dependency. Be thorough. Check:
- Source code imports and usage
- Configuration files
- Test files that exercise the dependency
- Build scripts or CI config that reference it

### Step 2: Review breaking changes from release notes

Use the release notes and PR body above to identify breaking changes. Do NOT read the dependency's own source code in `node_modules/`, `site-packages/`, or equivalent — that wastes turns on large libraries. The release notes are your primary source. Breaking changes include:
- Removed functions, classes, or methods
- Changed function signatures
- Dropped runtime version support (Python, Node, etc.)
- Changed default behavior
- Renamed exports

### Step 3: Cross-reference usage against breaking changes

For each breaking change from the release notes, check: does this codebase use the affected API? For each callsite, is there a test that would catch the breakage?

### Step 4: Check CI status

Are all CI checks passing on this PR? If not, what failed and is it related to the major bump?

### Step 5: Write your verdict

Create the file `.blender-verdict.json` using the **Write** tool (not
Bash — Bash runs in a sandbox and its file writes do not persist).
The file must contain valid JSON with this structure:

```json
{
  "safe": true,
  "confidence": "high",
  "reason": "Brief explanation of why this is safe or not safe",
  "breaking_changes": ["List each breaking change"],
  "affected_code": ["List files/functions affected by breaking changes"],
  "test_coverage": "Summary of test coverage for the dependency's usage"
}
```

**Confidence levels:**
- `high`: Breaking changes are well-understood. Usage is clear. Tests cover all callsites.
- `medium`: Usage is clear but test coverage has gaps, or some breaking changes are ambiguous.
- `low`: Cannot determine usage or breaking changes with confidence.

**safe = true** when:
- No breaking changes affect this codebase, OR
- All affected code paths are tested and CI passes

**safe = false** when:
- Breaking changes affect code in this repo, OR
- Test coverage gaps make it impossible to confirm safety, OR
- CI checks are failing

## Rules

- Do NOT edit any tracked files. Read and analyze only.
- Do NOT run `git` commands.
- Create ONLY `.blender-verdict.json` via the Write tool.
- Be conservative. When in doubt, mark as not safe.
