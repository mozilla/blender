<!-- blender:start — auto-generated, do not hand-edit -->
<!-- blender:start — auto-generated, do not hand-edit -->
# BLEnder — Agent Instructions (Delta)

Project-level guidance lives in `CLAUDE.md`. This file adds info BLEnder
needs that isn't already documented there.

## Languages & versions
- Python: `>=3.11` (declared in `pyproject.toml`, `[tool.ruff] target-version = "py311"`).
- Shell scripts (`scripts/*.sh`) are checked by `shellcheck`.
- GitHub Actions workflow YAML is checked by `actionlint`, `zizmor`, and `yamllint`.
- There is no Node.js component for the automation itself (the `docs/` dashboard is vanilla JS with no build step).

## Install dependencies
Tests and CI use [`uv`](https://github.com/astral-sh/uv):
```sh
uv sync --extra test
```
For an equivalent pip install:
```sh
pip install -e ".[dev,test]"
```

Lint-only tools (`ruff`, `yamllint`, `zizmor`) are installed via pip in CI;
`shellcheck` and `actionlint` are system / Go tools.

## Full CI check commands
The pre-push subset in `CLAUDE.md` covers Python only. The full CI in
`.github/workflows/ci.yml` runs six jobs — match each exactly when fixing
a failure:

| CI job        | Command                                              |
|---------------|------------------------------------------------------|
| `shellcheck`  | `shellcheck scripts/*.sh`                            |
| `actionlint`  | `actionlint` (installed via `go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12`) |
| `zizmor`      | `zizmor .github/workflows/`                          |
| `ruff`        | `ruff check scripts/` and `ruff format --check scripts/` |
| `yamllint`    | `yamllint -c .yamllint.yml .github/workflows/`       |
| `test`        | `uv run --extra test pytest --cov --cov-report=term-missing tests/` |

## Lint config notes
- `yamllint` config lives at `.yamllint.yml` (must be passed explicitly with `-c`).
- `ruff` is configured in `pyproject.toml` (`target-version = "py311"`, double quotes).
- No `.pre-commit-config.yaml`, no Husky / lint-staged — there are no commit hooks to work around.

## No code generation
No Glean, protobuf, GraphQL, or OpenAPI generators in this repo. Dependabot
PRs that touch Python deps in `pyproject.toml` / `scripts/requirements.txt`
do not require regenerating any artifacts.

## Dependency files Dependabot touches
- `pyproject.toml` — runtime + dev/test deps.
- `scripts/requirements.txt` — mirrors runtime pins from `pyproject.toml`; keep them in sync when bumping.
- `.github/workflows/*.yml` — pinned action SHAs and pinned tool versions (e.g. `actionlint@v1.7.12`).
<!-- blender:end -->
<!-- blender:end -->
