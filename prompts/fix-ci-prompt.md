# BLEnder: Fix CI failures on Dependabot PRs

## Context

{{PR_TITLE}}

Failing checks:
{{FAILING_CHECKS}}

## CI logs

{{CI_LOGS}}

{{INSTALL_ERROR}}

## Your task

Fix the CI failures caused by this dependency update.
Make the minimum change needed. Do not refactor unrelated code.

## Strategy

1. Consult the agent instructions prepended above for CI commands.
2. Run the failing check to reproduce the error.
3. Read the error output. Identify the root cause.
4. Make the fix. Run the check again to confirm.
5. If you cannot fix it, say so. Do not guess.
6. You have a limited number of turns. Be direct.

## Commit message

After fixing the issue, write a commit message to `.blender-commit-msg` using this format:

BLEnder fix(<dependency-name>): <1-line summary of what you fixed>

<Short explanation of the root cause and what you changed. A few sentences max.>

Write the file with the Edit tool. Do not include backticks or markdown formatting in the file.

Example:

BLEnder fix(typescript): add scrollMargin to IntersectionObserver mock

TypeScript 6.0 added scrollMargin to the IntersectionObserver interface.
The test mock was missing this property, causing a type error.
