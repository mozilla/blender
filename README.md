# BLEnder

BLEnder fixes failing CI on Dependabot pull requests. It reads the CI logs, runs Claude Code in a sandbox to make the fix, and commits the result. It can also auto-merge safe Dependabot PRs (patch/minor, high compatibility, no advisories).

## Install

BLEnder has a setup workflow that analyzes your repo and opens a PR with everything configured.

### Prerequisites

The BLEnder GitHub App must be installed on your org and have access to the target repo. The `mozilla/blender` repo needs three secrets:

- `BLENDER_APP_ID` -- the GitHub App ID
- `BLENDER_APP_PRIVATE_KEY` -- the GitHub App private key
- `ANTHROPIC_API_KEY` -- Anthropic API key for Claude Code

### Run setup

1. Go to [Actions](../../actions) in the `mozilla/blender` repo
2. Select **BLEnder Setup**
3. Click **Run workflow**
4. Enter the target repo (e.g. `mozilla/blurts-server`)
5. Click **Run workflow**

Setup does the following:

- Checks out the target repo
- Runs Claude Code to analyze the project (languages, CI config, test commands, linters)
- Generates three files tailored to the repo
- Opens a PR on the target repo

### Review the PR

The PR adds three files:

| File | Purpose |
|------|---------|
| `.github/blender/fix-dependabot-prompt.md` | Prompt template with repo-specific fix patterns |
| `.github/workflows/blender-fix-dependabot-pr.yml` | Caller workflow for CI fix |
| `.github/workflows/blender-automerge-dependabot.yml` | Caller workflow for auto-merge |

Review the prompt template. It should list the right test commands, linters, and formatters for your project. Edit it if needed.

### Add the secret

Before merging the PR, add `ANTHROPIC_API_KEY` to the target repo:

**Settings > Secrets and variables > Actions > New repository secret**

### Merge

Merge the PR. BLEnder is now installed.

## Quick start

### Fix a failing Dependabot PR

1. Go to **Actions** in your repo
2. Select **BLEnder Fix Dependabot CI**
3. Enter the PR number
4. Set dry run to `true` for the first attempt
5. Check the workflow logs to see what Claude would change
6. Run again with dry run `false` to commit the fix

### Auto-merge safe PRs

The auto-merge workflow runs on a schedule (if configured) or manually:

1. Go to **Actions** in your repo
2. Select **BLEnder Auto-merge Dependabot**
3. Set dry run to `true` to preview which PRs would merge
4. Run again with dry run `false` to approve and merge

## How it works

### Fix workflow

1. Checks out the Dependabot PR branch
2. Fetches failing checks and CI logs from the GitHub API
3. Sanitizes all inputs against prompt injection
4. Revokes `GH_TOKEN` from the environment (Claude cannot call GitHub)
5. Runs Claude Code in a sandbox (no network, no secrets)
6. Validates output: rejects changes to `.github/`, `.env`, `.circleci/`; detects nonce leaks; reverts cosmetic-only changes
7. Commits via the GitHub API (verified, signed by `github-actions[bot]`)

### Auto-merge workflow

Scans all open Dependabot PRs and merges those that pass five gates:

1. **Author** is `dependabot[bot]`
2. **CI** is green (all checks pass)
3. **Version bump** is patch or minor (no major)
4. **Compatibility score** >= 80% (from Dependabot's badge)
5. **No security advisories** affect the new version

## Inputs reference

### Fix workflow (`fix-dependabot-pr.yml`)

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `pr_number` | yes | | PR number to fix |
| `dry_run` | no | `true` | Skip commit when `true` |
| `python_version` | no | | Python version to install |
| `node_version` | no | | Node.js version to install |
| `install_command` | no | | Shell command to install dependencies |
| `submodules` | no | `false` | Checkout git submodules |
| `prompt_dir` | no | `.github/blender` | Path to prompt template directory |
| `repo_name` | no | | Display name for the repo |

### Auto-merge workflow (`automerge-dependabot.yml`)

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `dry_run` | no | `true` | Skip merge when `true` |

## Security

- Claude runs in a sandbox with no network access and no GitHub token
- All PR metadata is sanitized before entering the prompt
- Nonce-based leak detection catches prompt exfiltration attempts
- Changes to `.github/`, `.env`, and `.circleci/` are rejected
- Cosmetic-only changes (whitespace diffs) are reverted automatically
- Commits are created via the GitHub API, signed by `github-actions[bot]`
- All action references are pinned to commit SHAs
