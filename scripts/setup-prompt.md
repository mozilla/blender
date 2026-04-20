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

Create `{{OUTPUT_DIR}}/fix-dependabot-prompt.md` with this structure:

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

## Step 3: Generate the config file

Create `{{OUTPUT_DIR}}/blender.yml` with repo-specific settings. Determine:
- `repo_name`: a human-readable project name
- `node_version`: from `.nvmrc`, `.node-version`, `package.json` engines, CI config, or omit if not a Node project
- `python_version`: from `.python-version`, `pyproject.toml`, CI config, or omit if not a Python project
- `install_command`: the commands to install dependencies (e.g., `npm ci` or `pip install -r requirements.txt && cd frontend && npm ci`)

Use this format:

```yaml
repo_name: "<Project Name>"
node_version: "<version>"
python_version: "<version>"
install_command: "<command>"
```

Omit lines that are not needed (e.g., `python_version` for a pure Node project).

## Important

- Use the Write tool to create both files.
- Do not modify any existing files in the repo.
- Only create files inside `{{OUTPUT_DIR}}/`.
