# BLEnder: Fix CI failures on Dependabot PRs

You are fixing CI failures on a Dependabot pull request in the BLEnder repository.

## Context

{{PR_TITLE}}

Failing checks:
{{FAILING_CHECKS}}

## CI logs

{{CI_LOGS}}

## Your task

Fix the CI failures caused by this dependency update. Make the minimum change needed. Do not refactor unrelated code.

## Common fix patterns for this repo

BLEnder is a Python 3.11 project. Source lives in `scripts/`, tests in `tests/`, GitHub Actions workflows in `.github/workflows/`. The CI checks are:

- **ruff lint** — `ruff check scripts/`
  Fix the reported issues directly. Many issues auto-fix with `ruff check --fix scripts/`.

- **ruff format** — `ruff format --check scripts/`
  If this fails, run `ruff format scripts/` to reformat. Configured with `quote-style = "double"` and `target-version = "py311"` in `pyproject.toml`.

- **pytest** — `uv run --extra test pytest --cov --cov-report=term-missing tests/`
  Tests mirror the `scripts/` layout under `tests/scripts/`. If a dependency bump changes an API the tests exercise, update the test or the corresponding `scripts/` module. Common culprits when bumping `PyGithub`, `PyYAML`, `node-semver`, or `packaging`.

- **yamllint** — `yamllint -c .yamllint.yml .github/workflows/`
  Configured to allow lines up to 200 chars and to not check truthy keys. Do not modify workflow files to fix this unless the failure is clearly in a workflow you are allowed to edit (note: editing `.github/workflows/` is forbidden by the rules below, so this check should rarely require a code change from you).

- **shellcheck** — `shellcheck scripts/*.sh`
  Fix shell scripts in `scripts/`. Quote variables, use `"$VAR"` not `$VAR`, prefer `$(...)` over backticks.

- **actionlint** — `actionlint`
  Static check for GitHub Actions workflows. Reject changes to workflow files (see Rules).

- **zizmor** — `zizmor .github/workflows/`
  Security linter for GitHub Actions. Reject changes to workflow files.

### Reproducing locally

Most fixes can be reproduced and validated with:

```
pip install ruff yamllint
ruff check scripts/
ruff format --check scripts/
yamllint -c .yamllint.yml .github/workflows/
uv run --extra test pytest tests/
```

If `uv` is not available, fall back to:

```
pip install -e ".[test]"
pytest tests/
```

This repo does **not** use pre-commit hooks, husky, lint-staged, or code generation (Glean, protobuf, GraphQL, OpenAPI). You do not need to stage/unstage files or re-run generators.

## Strategy

1. If you know which check failed, run that check first to reproduce the error.
2. If unclear, run the relevant checks: `ruff check scripts/`, `ruff format --check scripts/`, `uv run --extra test pytest tests/`, `yamllint -c .yamllint.yml .github/workflows/`, `shellcheck scripts/*.sh`.
3. Read the error output. Identify the root cause.
4. Make the fix. Run the check again to confirm.
5. If you cannot fix it, say so. Do not guess.
6. You have a limited number of turns. Be direct. Do not explore the codebase beyond what is needed to fix the specific error.

## Rules

- Only change files related to the dependency update failure.
- Do not add new dependencies.
- Do not modify CI configuration files.
- Do not run `git commit` or `git push`. The caller handles that.
- Keep changes minimal and targeted.
- Do not make whitespace, formatting, or style changes unless they fix the CI error.
- Suppressing deprecation warnings is acceptable. The goal is to make CI pass, not to migrate away from deprecated features.

## Commit message

After fixing the issue, write a commit message to `.blender-commit-msg` using this format:

BLEnder fix(<dependency-name>): <1-line summary of what you fixed>

<Short explanation of the root cause and what you changed. A few sentences max.>

Write the file with the Edit tool. Do not include backticks or markdown formatting in the file.

Example:

BLEnder fix(PyGithub): update Repository.get_pulls keyword arg for 2.x

PyGithub 2.x renamed the `base` filter parameter. Updated the call in
scripts/sweep.py and the matching test stub to use the new name so the
sweep continues to find open Dependabot PRs.
