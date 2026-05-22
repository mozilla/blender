# BLEnder Setup: Generate config for {{REPO}}

You are setting up BLEnder (automated Dependabot CI fix) for this repository.

## Step 1: Explore the repo

Read these files to understand the project:
- Package manifests: `package.json`, `requirements.txt`, `Cargo.toml`, `Gemfile`, `go.mod`, etc.
- CI config: `.github/workflows/`, `.circleci/`, etc. — read the actual job steps and extract the exact commands each CI check runs
- Pre-commit / lint-staged hooks: `.pre-commit-config.yaml`, `.husky/`, `.lintstagedrc.*`, `lint-staged` config in `package.json` — these often enforce formatting that CI checks
- Runtime versions: `.python-version`, `.node-version`, `.nvmrc`, `.tool-versions`, etc.
- `README.md` (for project context)
- `pyproject.toml`, `tsconfig.json` (for linters/formatters in use)
- Code generation scripts: look for Glean, protobuf, GraphQL, OpenAPI generators — if a dependency update breaks generated code, the fix is to re-run the generator

Also read these existing agent instruction files (if any):
{{EXISTING_AGENT_FILES}}

Note what knowledge they already contain — CI commands, linters, install steps, etc. You will avoid duplicating this in Step 2.

## Step 2: Generate `.blender/agents.md`

Create `{{OUTPUT_DIR}}/agents.md` with repo knowledge BLEnder needs.

**If the repo has no existing agent instruction files**: generate comprehensive content:
- Project name, languages, runtime versions
- How to install dependencies
- Exact CI check commands (extracted from workflow YAML)
- Pre-commit hook info and stage/unstage workaround
- Code generation commands (Glean, protobuf, etc.)

**If the repo has existing agent files** (CLAUDE.md, AGENTS.md, etc.): generate only the **delta** — knowledge BLEnder needs that isn't already documented. Skip anything the existing files cover.

## Step 3: Generate the config file

Create `{{OUTPUT_DIR}}/blender.yml` with repo-specific settings. Determine:
- `repo_name`: a human-readable project name
- `node_version`: major version only (e.g., `"22"` not `"22.15.0"`), from `.nvmrc`, `.node-version`, `package.json` engines, CI config, or omit if not a Node project
- `python_version`: major.minor only (e.g., `"3.11"` not `"3.11.9"`), from `.python-version`, `pyproject.toml`, CI config, or omit if not a Python project
- `install_command`: the commands to install dependencies (e.g., `npm ci` or `pip install -r requirements.txt && cd frontend && npm ci`)

Use this format:

```yaml
repo_name: "<Project Name>"
node_version: "<version>"
python_version: "<version>"
install_command: "<command>"
```

Omit lines that are not needed (e.g., `python_version` for a pure Node project).

### Optional: BLEnder overrides

Add overrides for default sweep/automerge/fix settings.
All fields are optional. Omit them to use defaults.

```yaml
automerge:
  min_compatibility_score: 90  # default: 80
  allow_major: false           # default: false
  check_advisories: true       # default: true
fix:
  dry_run: false               # default: false
  max_claude_turns: 30         # default: 30
  max_budget_usd: 3.00         # default: 2.00
```

These overrides are merged on top of BLEnder's `config/defaults.yml` at runtime.

## Important

- Use the Write tool to create all files.
- Do not modify any existing files in the repo.
- Only create files inside `{{OUTPUT_DIR}}/`.
- Setup generates 2 files: `agents.md` and `blender.yml`.
