# BLEnder Setup: Generate config for {{REPO}}

You are setting up BLEnder (automated Dependabot CI fix) for this repository.

## Step 1: Explore the repo

Read these files to understand the project:
- Package manifests: `package.json`, `requirements.txt`, `Cargo.toml`, `Gemfile`, `go.mod`, etc.
- CI config: `.github/workflows/`, `.circleci/`, etc.
- Runtime versions: `.python-version`, `.node-version`, `.nvmrc`, `.tool-versions`, etc.
- `CLAUDE.md`, `README.md` (for project context)
- `pyproject.toml`, `tsconfig.json` (for linters/formatters in use)

## Step 2: Generate the prompt template

Create `.github/blender/fix-dependabot-prompt.md` with this structure:

```
# BLEnder: Fix CI failures on Dependabot PRs

You are fixing CI failures on a Dependabot pull request in the <project name> repository.

## Context

{{PR_TITLE}}

Failing checks:
{{FAILING_CHECKS}}

## CI logs

{{CI_LOGS}}

## Your task

Fix the CI failures caused by this dependency update. Make the minimum change needed. Do not refactor unrelated code.

## Common fix patterns for this repo

<List the linters, formatters, type checkers, and test commands specific to this repo.
Include the exact commands to run each one.>

## Strategy

1. If you know which check failed, run that check first to reproduce the error.
2. If unclear, run the relevant checks: <list repo-specific check commands>.
3. Read the error output. Identify the root cause.
4. Make the fix. Run the check again to confirm.
5. If you cannot fix it, say so. Do not guess.

## Rules

- Only change files related to the dependency update failure.
- Do not add new dependencies.
- Do not modify CI configuration files.
- Do not run `git commit` or `git push`. The caller handles that.
- Keep changes minimal and targeted.
- Suppressing deprecation warnings is acceptable. The goal is to make CI pass, not to migrate away from deprecated features.

## Commit message

After fixing the issue, write a commit message to `.blender-commit-msg` using this format:

BLEnder fix(<dependency-name>): <1-line summary of what you fixed>

<Short explanation of the root cause and what you changed. A few sentences max.>

Write the file with the Edit tool. Do not include backticks or markdown formatting in the file.
```

Tailor the "Common fix patterns" section based on what you find in the repo.

## Step 3: Generate the caller workflows

### `.github/workflows/blender-fix-dependabot-pr.yml`

Generate a thin caller workflow. Determine:
- `python_version`: from `.python-version`, `pyproject.toml`, CI config, or skip if not a Python project
- `node_version`: from `.nvmrc`, `.node-version`, `package.json` engines, CI config, or skip if not a Node project
- `install_command`: the commands to install dependencies (e.g., `pip install -r requirements.txt && cd frontend && npm ci`)
- `submodules`: 'true' if the repo uses git submodules, 'false' otherwise
- `repo_name`: a human-readable project name

Use this template:

```yaml
name: BLEnder Fix Dependabot CI
on:
  workflow_dispatch:
    inputs:
      pr_number: { description: 'PR number to fix', required: true }
      dry_run: { description: 'Dry run', default: 'true' }
permissions: {}
jobs:
  fix:
    uses: mozilla/blender/.github/workflows/fix-dependabot-pr.yml@v1
    with:
      pr_number: ${{ inputs.pr_number }}
      dry_run: ${{ inputs.dry_run }}
      python_version: '<version or empty>'
      node_version: '<version or empty>'
      install_command: '<command>'
      submodules: '<true or false>'
      repo_name: '<Project Name>'
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Remove `python_version` or `node_version` lines if the project does not use that language.

### `.github/workflows/blender-automerge-dependabot.yml`

```yaml
name: BLEnder Auto-merge Dependabot
on:
  workflow_dispatch:
    inputs:
      dry_run: { description: 'Dry run', default: 'true' }
permissions: {}
jobs:
  automerge:
    uses: mozilla/blender/.github/workflows/automerge-dependabot.yml@v1
    with:
      dry_run: ${{ inputs.dry_run }}
```

## Important

- Use the Write tool to create all three files.
- Do not modify any existing files in the repo.
- Do not create any files outside `.github/blender/` and `.github/workflows/`.
