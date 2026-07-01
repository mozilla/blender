# BLEnder

<img src="docs/assets/dino-avatar.png" alt="BLEnder" width="200" />

## What BLEnder does

Software projects depend on hundreds of libraries. Those libraries release updates constantly. Each update creates a small task: check the change, run the tests, merge it in. Multiply that across dozens of projects and the backlog grows fast.

BLEnder handles it. It watches your projects for dependency updates, decides which ones are safe, and merges them. For big updates that might change how a library works, BLEnder reviews the change to merge it or flag it for you to review. When an update breaks something, BLEnder reads the error, and commits a fix for you to review. 

**One install covers all the orgs.** BLEnder runs on its own. Your projects don't need secrets or processes to get started beyond a short onboarding step.

### At a glance

- **Safe small updates get merged.** Small, compatible updates with clean tests are approved and merged with no human involvement.
- **Major updates get reviewed.** Major version changes are analyzed for breaking changes. Safe ones merge. Uncertain ones get a written report for a human to decide.
- **Broken updates get fixed.** When an update breaks the build, BLEnder reads the errors, writes a code fix, and commits it.
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

All five must pass. If any check fails, the update waits or gets routed elsewhere.

### Major version review

Major version bumps can change how a library works. When BLEnder sees a major update, it uses [Claude Code](https://claude.com/product/claude-code) to:

1. Read the library's release notes and new code
2. Scan your code for affected areas
3. Check that your tests cover the affected areas

- If BLEnder determines the major update is low-risk, it merges the major update.
- If not, BLEnder adds a comment with a detailed report for review.

### Fix

When BLEnder sees an update the breaks the repos checks, BLEnder:

1. Collects the test output and error logs
2. Sends them to [Claude Code](https://claude.com/product/claude-code) (Anthropic's AI) inside a locked-down sandbox with no network access and no credentials
3. Validates the fix — rejects changes to sensitive files and scans for leaked secrets
4. Commits the fix to the update

The AI cannot access the internet, call any APIs, or see any credentials. Its output is validated before anything is committed.

### Security alert investigation

The sweep also picks up open [Dependabot security alerts](https://docs.github.com/en/code-security/dependabot/dependabot-alerts/about-dependabot-alerts). For each one, BLEnder reads the codebase in a sandbox to judge whether the vulnerability actually reaches your project, then acts on the verdict:

- **Unaffected** — dismisses the alert (when `dismiss_unaffected` is on) or opens a lock-file bump PR for a clean transitive fix.
- **Affected** — opens a private security advisory and a fork where it drafts a fix.

You can tune this with the `investigate` config: turn it off per repo, set a minimum `severity_threshold`, or cap Claude's turns and budget.

### Auto-engineer (experimental)

BLEnder can also take on issue-driven code changes: label an issue, and it plans, implements, and self-reviews the work across separate steps. This is **off by default** and broader than the Dependabot flow. Enable it per repo under the `auto_engineer` config.

---

## Dashboard

BLEnder has a [live mission control dashboard](https://mozilla.github.io/blender/) that tracks sweeps, fixes, merges, and reviews in real time.

---

## Getting started

### 1. Install the GitHub App

Install the BLEnder GitHub App on your organization. Grant it access to the repositories you want covered.

### 2. Run onboarding

Go to **BLEnder Setup** in the Actions tab and run the workflow for your project. BLEnder will analyze the project and open a pull request with a tailored configuration.

### 3. Review the onboarding pull request

The pull request adds a `.blender/` directory with two files:

- **`blender.yml`** — project metadata (name, language versions, install command)
- **`agents.md`** — agent instructions BLEnder uses when fixing broken updates: install steps, exact CI and test commands, linters, and other repo knowledge

If your repo has no existing agent instructions file, the PR also symlinks `CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md` to `agents.md`.

Review that the configuration looks right and merge it. BLEnder starts working on the next sweep.

---

## Configuration

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

### Agent instructions (`.blender/agents.md`)

Onboarding generates this file. It holds the repo knowledge BLEnder needs to fix a broken update: install steps, the exact CI and test commands, linters, and language versions. When the repo already has an agent instructions file (like `CLAUDE.md`), BLEnder writes only the delta — what those files don't already cover.

### Default settings

BLEnder ships with defaults in [`config/defaults.yml`](config/defaults.yml):

```yaml
automerge:
  dry_run: false
  allow_major: false
  review_major: true
  min_compatibility_score: 70
  check_advisories: true

fix:
  dry_run: false
  max_claude_turns: 30
  max_budget_usd: 2.00
  max_fix_attempts: 3

investigate:
  enabled: true
  dry_run: false
  max_claude_turns: 20
  max_budget_usd: 1.50
  severity_threshold: ""      # "", "low", "medium", "high", or "critical"
  dismiss_unaffected: false

auto_engineer:                # experimental, off by default
  enabled: false
  dry_run: true
  issue_label: "auto-engineer"
  trusted_author_associations: "OWNER"
  forbidden_paths: ".github/ .env .circleci/"
  max_plan_turns: 20
  max_plan_budget_usd: 1.50
  max_implement_turns: 40
  max_implement_budget_usd: 4.00
  max_self_review_turns: 15
  max_self_review_budget_usd: 1.00
```

Override any of these in your project's `.blender/blender.yml`.

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
