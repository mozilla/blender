# BLEnder — Claude Instructions

## What this repo is
GitHub Actions automation for Mozilla's Dependabot workflow. The actions
run in this repo but target other repos. BLEnder sweeps for open
Dependabot PRs, reviews major bumps, fixes CI failures, and auto-merges
passing PRs.

## Repo layout
- `.github/workflows/` — GitHub Actions workflow YAML files
- `scripts/` — Python and shell scripts that workflows call
- `config/` — default configuration (`defaults.yml`)
- `prompts/` — Claude prompt templates used by workflows
- `tests/` — pytest suite (mirrors `scripts/` structure)
- `docs/` — dashboard web app (has its own `CLAUDE.md`)

## Key files
- `scripts/automerge_dependabot.py` — main orchestration script
- `scripts/sweep.py` — finds open Dependabot PRs across repos
- `scripts/post_major_review.py` — reviews major version bumps
- `scripts/github_utils.py` — shared GitHub API helpers
