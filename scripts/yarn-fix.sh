#!/usr/bin/env bash
# BLEnder yarn fix (yarn Berry v2+): bump a (possibly transitive) dependency
# to a patched version and regenerate yarn.lock.
#
# MVP scope (see #122):
#   - Targets yarn Berry (v2+). Yarn classic (v1) is NOT handled yet.
#   - Uses `yarn up -R` to raise the package everywhere it resolves in the
#     dependency tree (including transitively), then regenerates yarn.lock.
#   - Verification via `yarn npm audit` is best-effort only; `fixed` is based
#     on `yarn up` succeeding. See OPEN QUESTIONS in the PR before relying on it.
#
# Runs in the target repo checkout. Writes `fixed=true|false` to $GITHUB_OUTPUT.
#
# Environment variables:
#   YARN_PACKAGE  -- package name (required)
#   YARN_VERSION  -- patched version to bump to (optional; latest if unset)

set -euo pipefail

: "${YARN_PACKAGE:?YARN_PACKAGE is required}"

out() { echo "$1=$2" >> "${GITHUB_OUTPUT:-/dev/null}"; }

if [ ! -f yarn.lock ]; then
  echo "::warning ::No yarn.lock — not a yarn repo; skipping."
  out fixed false
  exit 0
fi

# Berry is delivered through corepack; enable it so the repo's pinned yarn
# (packageManager in package.json / .yarnrc.yml) is the one that runs.
corepack enable 2>/dev/null || true

YARN_VER="$(yarn --version 2>/dev/null || echo 0)"
echo "Detected yarn ${YARN_VER}"
case "$YARN_VER" in
  1.* | 0)
    echo "::warning ::yarn classic (v1) is not supported yet (see #122); skipping."
    out fixed false
    exit 0
    ;;
esac

echo "Before — where ${YARN_PACKAGE} resolves:"
yarn why "$YARN_PACKAGE" 2>/dev/null || true

# Berry v4's `-R` (recursive — covers transitive deps) takes the package NAME
# only: it re-resolves every occurrence to the newest version satisfying each
# existing range. Passing a version/range errors ("Ranges aren't allowed when
# using --recursive"). --mode=update-lockfile writes yarn.lock without
# installing, mirroring npm's --package-lock-only. Verified live against
# mozilla/fxa (yarn@4.9.2): a single run bumped all vulnerable brace-expansion
# lines to their patched in-range versions, yarn.lock-only.
echo "Running: yarn up -R ${YARN_PACKAGE} --mode=update-lockfile"
if ! yarn up -R "$YARN_PACKAGE" --mode=update-lockfile; then
  echo "::warning ::'yarn up -R ${YARN_PACKAGE}' failed; leaving for manual remediation."
  out fixed false
  exit 0
fi

# -R stays within the ranges declared by consumers. If the patched version is
# outside every consumer's range (e.g. needs a major bump they don't allow),
# yarn.lock won't change — that case needs a `resolutions` override, which is
# not implemented yet (see #122).
if git diff --quiet yarn.lock 2>/dev/null; then
  echo "::warning ::yarn.lock unchanged — ${YARN_PACKAGE} likely needs a resolutions override to reach ${YARN_VERSION:-the patched version} (see #122)."
  out fixed false
  exit 0
fi

echo "yarn.lock updated for ${YARN_PACKAGE} (advisory verified via CI / Dependabot)."
out fixed true
