# BLEnder

Dependabot PRs break CI. BLEnder fixes them.

It reads the CI logs, runs Claude Code in a sandbox, and commits the fix. It can also auto-merge safe PRs — patch or minor bumps with high compatibility and no advisories.

Everything runs from this repo via a GitHub App. No workflows or secrets needed in the target repo.

## Install & quick start

1. Install the BLEnder GitHub App on your org. Grant it access to the target repo.
2. Go to [BLEnder Setup](https://github.com/mozilla/blender/actions/workflows/build-setup.yml) → **Run workflow** → enter the target repo (e.g. `mozilla/blurts-server`)
3. Review the PR that BLEnder opens on your repo. It adds a `.blender/` directory with config and a prompt template. Check that the prompt lists the right test commands, linters, and formatters.
4. Merge the PR. BLEnder will start scanning your repo on its next sweep.

## Config

### `.blender/blender.yml`

Setup generates this file for your repo. A minimal example:

```yaml
repo_name: "My Project"
install_command: "npm ci"
```

Available fields:

| Field | Required | Description |
|-------|----------|-------------|
| `repo_name` | yes | Human-readable project name |
| `install_command` | no | Command to install dependencies |
| `node_version` | no | Node.js version for `setup-node` |
| `python_version` | no | Python version for `setup-python` |

Omit fields that don't apply.

### `.blender/fix-dependabot-prompt.md`

Prompt template with `{{PR_TITLE}}`, `{{FAILING_CHECKS}}`, and `{{CI_LOGS}}` placeholders. Lists the repo's test commands, linters, and common fix patterns.

### Default settings

BLEnder ships with defaults in `config/defaults.yml`:

```yaml
automerge:
  allow_major: false
  min_compatibility_score: 80
  check_advisories: true

fix:
  dry_run: false
  max_claude_turns: 30
  max_budget_usd: 2.00
```

Per-repo overrides go in the target repo's `.blender/blender.yml`.

## Manual triggers

### Fix a failing Dependabot PR

1. Go to [BLEnder Fix](https://github.com/mozilla/blender/actions/workflows/fix-dependabot-pr.yml)
2. Click **Run workflow**
3. Enter the target repo and PR number
4. Set dry run to `true` first to preview
5. Run again with dry run `false` to commit the fix

### Auto-merge safe PRs

1. Go to [BLEnder Auto-merge](https://github.com/mozilla/blender/actions/workflows/chore-automerge-dependabot-prs.yml)
2. Click **Run workflow**
3. Enter the target repo
4. Set dry run to `true` to preview
5. Run again with dry run `false` to merge

---

## How it works

### Sweep

A scheduled job runs every 30 minutes. It authenticates as the BLEnder GitHub App, lists all installations, and checks each repo for work:

- **Failing Dependabot PRs** → triggers a fix workflow
- **Green Dependabot PRs** that pass safety gates → triggers an auto-merge workflow

The sweep can also be triggered manually from [Scheduled Sweep](https://github.com/mozilla/blender/actions/workflows/scheduled-sweep.yml).

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

Checks all open Dependabot PRs against five gates:

1. **Author** is `dependabot[bot]`
2. **CI** is green
3. **Version bump** is patch or minor
4. **Compatibility score** >= 80%
5. **No security advisories** on the new version

PRs that pass all five gates get approved and merged.

### Security model

- Claude runs in a sandbox. No network. No GitHub token.
- PR metadata is sanitized before it enters the prompt.
- Leaked API keys and nonces in the diff abort the run.
- Changes to `.github/`, `.env`, and `.circleci/` are rejected.
- Whitespace-only changes are reverted.
- Claude's output is suppressed from job logs by default.
- Commits are signed by `github-actions[bot]` via the API.
- All action references are pinned to commit SHAs.
- Target repos never hold the Anthropic API key.
