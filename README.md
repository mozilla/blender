# BLEnder

Dependabot PRs break CI. BLEnder fixes them.

It reads the CI logs, runs Claude Code in a sandbox, and commits the fix. It can also auto-merge safe PRs — patch or minor bumps with high compatibility and no advisories.

Config lives in each target repo under `.blender/`. No workflows or secrets needed in the target repo. Everything runs from this repo via a GitHub App token.

## Add a repo

### Prerequisites

Install the BLEnder GitHub App on your org. Give it access to the target repo.

### Run setup

1. Go to [BLEnder Setup](https://github.com/mozilla/blender/actions/workflows/dispatch-setup.yml)
2. Click **Run workflow**
3. Enter the target repo (e.g. `mozilla/blurts-server`)
4. Click **Run workflow**

Setup will:

- Check out the target repo
- Run Claude Code to analyze the project
- Generate a config and prompt template
- Open a PR on the **target repo**

### Review the PR

The PR adds a `.blender/` directory to the target repo:

| File | Purpose |
|------|---------|
| `.blender/blender.yml` | Runtime versions, install command, repo name |
| `.blender/fix-dependabot-prompt.md` | Prompt template with fix patterns for the repo |

Review the prompt template. It should list the right test commands, linters, and formatters. Edit it if needed.

### Merge

Merge the PR. The repo is onboarded.

## Quick start

### Fix a failing Dependabot PR

1. Go to [BLEnder Fix](https://github.com/mozilla/blender/actions/workflows/dispatch-fix.yml)
2. Click **Run workflow**
3. Enter the target repo and PR number
4. Set dry run to `true`
5. Check the logs to see what Claude would change
6. Run again with dry run `false` to commit the fix

### Auto-merge safe PRs

1. Go to [BLEnder Auto-merge](https://github.com/mozilla/blender/actions/workflows/dispatch-automerge.yml)
2. Click **Run workflow**
3. Enter the target repo
4. Set dry run to `true` to preview
5. Run again with dry run `false` to merge

## How it works

### Fix workflow

1. Generate a GitHub App token for the target repo
2. Check out the Dependabot PR branch
3. Read config from `.blender/blender.yml` in the target repo
4. Install dependencies per config
5. Fetch failing checks and CI logs from the GitHub API
6. Sanitize inputs against prompt injection
7. Revoke the GitHub token — Claude cannot call GitHub
8. Run Claude Code in a sandbox — no network, no secrets
9. Reject changes to `.github/`, `.env`, `.circleci/`
10. Detect leaked nonces and API keys in the diff
11. Revert whitespace-only changes
12. Commit via the GitHub API, signed by `github-actions[bot]`

### Auto-merge workflow

Check all open Dependabot PRs against five gates:

1. **Author** is `dependabot[bot]`
2. **CI** is green
3. **Version bump** is patch or minor
4. **Compatibility score** >= 80%
5. **No security advisories** on the new version

PRs that pass all five gates get approved and merged.

## Per-repo config

Each target repo has a `.blender/` directory with:

### `.blender/blender.yml`

```yaml
repo_name: "Project Name"
node_version: "20.20.x"
python_version: "3.11"
install_command: "npm ci"
```

All fields except `repo_name` are optional. Omit what you don't need.

### `.blender/fix-dependabot-prompt.md`

Prompt template with `{{PR_TITLE}}`, `{{FAILING_CHECKS}}`, and `{{CI_LOGS}}` placeholders. Lists the repo's test commands, linters, and common fix patterns.

## Security

- Claude runs in a sandbox. No network. No GitHub token.
- PR metadata is sanitized before it enters the prompt.
- Leaked API keys and nonces in the diff abort the run.
- Changes to `.github/`, `.env`, and `.circleci/` are rejected.
- Whitespace-only changes are reverted.
- Claude's output is suppressed from job logs by default.
- Commits are signed by `github-actions[bot]` via the API.
- All action references are pinned to commit SHAs.
- Target repos never hold the Anthropic API key.
