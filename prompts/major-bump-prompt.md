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

### Step 2: Read the dependency source code

Read the installed dependency code directly (in `node_modules/`, `site-packages/`, or equivalent) to understand what changed between versions. Compare the public API surface.

### Step 3: Identify test coverage

For each callsite you found, determine:
- Is there a test that exercises this code path?
- Would the test catch a breaking change in the dependency's behavior?

### Step 4: Review breaking changes

From the release notes, PR body, and the dependency source code, identify all breaking changes. This includes:
- Removed functions, classes, or methods
- Changed function signatures
- Dropped runtime version support (Python, Node, etc.)
- Changed default behavior
- Renamed exports

### Step 5: Cross-reference

For each breaking change, check: does this codebase use the affected API? If yes, would existing tests catch the breakage?

### Step 6: Check CI status

Are all CI checks passing on this PR? If not, what failed and is it related to the major bump?

### Step 7: Write your verdict

Write your verdict to `.blender-verdict.json` using the Bash tool:

```bash
cat > .blender-verdict.json << 'VERDICT_EOF'
{
  "safe": true,
  "confidence": "high",
  "reason": "Brief explanation of why this is safe or not safe",
  "breaking_changes": ["List each breaking change"],
  "affected_code": ["List files/functions affected by breaking changes"],
  "test_coverage": "Summary of test coverage for the dependency's usage"
}
VERDICT_EOF
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
- Write ONLY `.blender-verdict.json` via Bash.
- Be conservative. When in doubt, mark as not safe.
