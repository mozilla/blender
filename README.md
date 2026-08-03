# BLEnder

<img src="docs/assets/dino-avatar.png" alt="BLEnder" width="200" />

## What BLEnder does

Software projects depend on hundreds of libraries. Those libraries release updates constantly. Each update creates a small task: check the change, run the tests, merge it in. Multiply that across dozens of projects and the backlog grows fast.

BLEnder handles it. It watches your projects for dependency updates, decides which ones are safe, and merges them. For big updates that might change how a library works, BLEnder reviews the change to merge or flag it for you to review. When an update breaks something, BLEnder reads the error, and commits a fix for you to review. 

BLEnder runs on its own. Your projects don't need secrets or processes to get started beyond [a short onboarding step](#getting-started).

### At a glance

- **Merges safe small updates.** Small, compatible updates with clean tests are approved and merged with no human involvement.
- **Reviews major updates.** Major version changes are analyzed for breaking changes. Safe ones merge. Uncertain ones get a written report for a maintainer to decide.
- **Fixes broken updates.** When an update breaks the build, BLEnder reads the errors, writes a code fix, and adds the fix to the update PR.
- **Triages security alerts**. BLEnder investigates dependabot security alerts to see if your code actually uses the vulnerable dependency code. 
- **Everything is auditable.** Every decision is posted as a comment on the update. Nothing happens in the dark.

---

## How it works

BLEnder sweeps your projects every 30 minutes looking for dependency updates from [Dependabot](https://docs.github.com/en/code-security/getting-started/dependabot-quickstart-guide). Each update goes through one of three paths:

### Auto-merge

For patch and minor updates, BLEnder checks:

3. The version change is small (patch or minor)
1. The update was created by Dependabot
2. All tests pass
4. The library's compatibility score is 70% or higher
5. No security advisories affect the new version

When all five checks pass, BLEnder marks the PR to auto-merge. If any check fails, BLEnder leaves a comment.

### Major version review

Major version bumps can change how a library works. When BLEnder sees a major update, it uses a locked-down, sandboxed [Claude Code](https://claude.com/product/claude-code) to:

1. Read the library's release notes and new code
2. Scan your code for affected areas
3. Check that your tests cover the affected areas

- If BLEnder determines the major update is low-risk, it merges the major update.
- If not, BLEnder adds a comment with a detailed report for review.

### Fix

When BLEnder sees an update the breaks the repos checks, BLEnder:

1. Collects the test output and error logs
2. Sends them to a locked-down, sandboxed [Claude Code](https://claude.com/product/claude-code) to create a fix.
3. Validates the fix.
4. Commits the fix to the update

The AI cannot access the internet, call any APIs, or see any credentials. Its output is validated before anything is committed.

### Security alert investigation

The sweep also picks up open [Dependabot security alerts](https://docs.github.com/en/code-security/dependabot/dependabot-alerts/about-dependabot-alerts). For each one, BLEnder reads the codebase in a sandbox to judge whether the vulnerability actually reaches your project, then acts on the verdict:

- **Unaffected** — dismisses the alert (when `dismiss_unaffected` is on) or opens a lock-file bump PR for a clean transitive fix.
- **Affected** — opens a private security advisory and a fork where it creates a fix.

You can tune this with the `investigate` config: turn it off per repo, set a minimum `severity_threshold`, or cap Claude's turns and budget.

---

## Dashboard

BLEnder has a [live mission control dashboard](https://mozilla.github.io/blender/) that tracks sweeps, fixes, merges, and reviews in real time.

---

## Getting started

### 1. Install the GitHub App

Install the BLEnder GitHub App on your organization. Grant it access to the repositories you want covered.

### 2. Run onboarding

Run [the Update BLEnder Config workflow in the BLEnder Actions](https://github.com/mozilla/blender/actions/workflows/build-setup.yml) workflow for your repo. BLEnder will analyze the project and open an onboarding pull request in the repo.

### 3. Review the onboarding pull request

The pull request adds a `.blender/` directory with two files:

- **`blender.yml`** — the BLEnder config file. (See [below](#project-config-blenderblenderyml))
- **`agents.md`** — agent instructions BLEnder will use. (See [below](#agent-instructions-blenderagentsmd))

If your repo has no existing agent instructions file, the PR also symlinks `CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md` to `agents.md`.

Review that the configuration looks right and merge it. BLEnder starts working on the next sweep.

---

## Configuration

### Default config

BLEnder's defaults are in its own [`config/defaults.yml`](config/defaults.yml) file. You may override any of these in your repo's `.blender/blender.yml` project config.

### Project config (`.blender/blender.yml`)

Onboarding generates this file. A minimal example:

```yaml
repo_name: "My Project"
install_command: "npm ci"
```

Available fields:

| Field | Required | Description |
|-------|----------|-------------|
| `repo_name` | yes | Human-readable project name |
| `install_command` | no | Command to install dependencies |
| `node_version` | no | Node.js version |
| `python_version` | no | Python version |

Omit fields that don't apply.

You may also override any of BLEnder's [default configs](#default-config) in your repo's `.blender/blender.yml` project config.

### Agent instructions (`.blender/agents.md`)

Onboarding generates this file. It holds the repo knowledge BLEnder needs to fix a broken update: install steps, the exact CI and test commands, linters, and language versions. When the repo already has an agent instructions file (like `CLAUDE.md`), BLEnder writes only the delta — what those files don't already cover.


---

## Manual triggers

All workflows run manually from the Actions tab. Every one except Update BLEnder Config takes a dry-run option to preview before committing.

| Workflow | What it does |
|----------|-------------|
| **Scheduled Sweep** | Scan all projects for work |
| **Fix Dependabot PR** | Fix a specific failing update |
| **Auto-merge Dependabot PRs** | Merge safe updates for a project |
| **Review Major Update** | Evaluate a major version bump |
| **Investigate Security Alert** | Assess whether an alert affects a project |
| **Auto-Engineer** | Plan and implement an issue-labeled change |
| **Update BLEnder Config** | Onboard a new project |

Set dry run to `true` to preview what BLEnder would do without making changes. Update BLEnder Config has no dry-run — it opens a pull request you review before merging.

---

## Security model

- **Sandboxed AI.** Claude runs with no network access and no credentials. The GitHub token is revoked before Claude starts.
- **Input sanitization.** Update metadata is scrubbed for injection attempts before it enters the prompt.
- **Secret detection.** Diffs are scanned for leaked API keys and cryptographic nonces. Any detection aborts the run.
- **Restricted file changes.** Changes to workflow files, environment files, and CI config are rejected.
- **Signed commits.** All commits are signed and attributed to `github-actions[bot]`.
- **Pinned dependencies.** All action references use commit SHA pins, not version tags.
- **No secrets in target projects.** The API key lives in BLEnder, not in your project.

---

## Repo layout

```
.github/workflows/   GitHub Actions workflows
scripts/             Python and shell scripts
config/              Default configuration
prompts/             Prompt templates for Claude
tests/               Test suite
docs/                Dashboard web app
```
