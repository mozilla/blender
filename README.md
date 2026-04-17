# BLEnder

Dependabot PRs break CI. BLEnder fixes them.

It reads the CI logs, runs Claude Code in a sandbox, and commits the fix. It can also auto-merge safe PRs — patch or minor bumps with high compatibility and no advisories.

## Install

Run the BLEnder setup workflow. It analyzes your repo and opens a PR for you.

### Prerequisites

Install the BLEnder GitHub App on your org. Give it access to the target repo.

### Run setup

1. Go to [BLEnder Setup](https://github.com/mozilla/blender/actions/workflows/setup.yml)
2. Click **Run workflow**
4. Enter the target repo (e.g. `mozilla/blurts-server`)
5. Click **Run workflow**

Setup will:

- Check out the target repo
- Run Claude Code to analyze the project
- Generate three files for the repo
- Open a PR

### Review the PR

The PR adds three files:

| File | Purpose |
|------|---------|
| `.github/blender/fix-dependabot-prompt.md` | Prompt template with fix patterns for your repo |
| `.github/workflows/blender-fix-dependabot-pr.yml` | Caller workflow for CI fix |
| `.github/workflows/blender-automerge-dependabot.yml` | Caller workflow for auto-merge |

Especially review the prompt template. It should list the right test commands, linters, and formatters. Edit it if needed.

### Add the secret

Add `ANTHROPIC_API_KEY` to the target repo before you merge:

**Settings > Secrets and variables > Actions > New repository secret**

### Merge

Merge the PR. BLEnder is installed.

## Quick start

### Fix a failing Dependabot PR

1. Go to **Actions** in your repo
2. Select **BLEnder Fix Dependabot CI**
3. Enter the PR number
4. Set dry run to `true`
5. Check the logs to see what Claude would change
6. Run again with dry run `false` to commit the fix

### Auto-merge safe PRs

Run the auto-merge workflow on a schedule or by hand:

1. Go to **Actions** in your repo
2. Select **BLEnder Auto-merge Dependabot**
3. Set dry run to `true` to preview
4. Run again with dry run `false` to merge

## How it works

### Fix workflow

1. Check out the Dependabot PR branch
2. Fetch failing checks and CI logs from the GitHub API
3. Sanitize inputs against prompt injection
4. Revoke `GH_TOKEN` from the environment — Claude cannot call GitHub
5. Run Claude Code in a sandbox — no network, no secrets
6. Reject changes to `.github/`, `.env/`, `.circleci/`
7. Detect leaked nonces and API keys in the diff
8. Revert whitespace-only changes
9. Commit via the GitHub API, signed by `github-actions[bot]`

### Auto-merge workflow

Check all open Dependabot PRs against five gates:

1. **Author** is `dependabot[bot]`
2. **CI** is green
3. **Version bump** is patch or minor
4. **Compatibility score** >= 80%
5. **No security advisories** on the new version

PRs that pass all five gates get approved and merged.

## Inputs

### Fix workflow (`fix-dependabot-pr.yml`)

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `pr_number` | yes | | PR number to fix |
| `dry_run` | no | `true` | Skip commit when `true` |
| `python_version` | no | | Python version to install |
| `node_version` | no | | Node.js version to install |
| `install_command` | no | | Command to install dependencies |
| `submodules` | no | `false` | Check out git submodules |
| `prompt_dir` | no | `.github/blender` | Path to prompt template |
| `repo_name` | no | | Display name for the repo |
| `verbose` | no | `false` | Print Claude's full output |

### Auto-merge workflow (`automerge-dependabot.yml`)

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `dry_run` | no | `true` | Skip merge when `true` |

## Security

- Claude runs in a sandbox. No network. No GitHub token.
- PR metadata is sanitized before it enters the prompt.
- Leaked API keys and nonces in the diff abort the run.
- Changes to `.github/`, `.env`, and `.circleci/` are rejected.
- Whitespace-only changes are reverted.
- Claude's output is suppressed from job logs by default.
- Commits are signed by `github-actions[bot]` via the API.
- All action references are pinned to commit SHAs.
