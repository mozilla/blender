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

# `-R` raises the dependency recursively (transitive deps included).
TARGET="$YARN_PACKAGE"
if [ -n "${YARN_VERSION:-}" ]; then
  TARGET="${YARN_PACKAGE}@npm:^${YARN_VERSION}"
fi
echo "Running: yarn up -R ${TARGET}"
if ! yarn up -R "$TARGET"; then
  echo "::warning ::'yarn up -R ${TARGET}' failed; leaving for manual remediation."
  out fixed false
  exit 0
fi

# Best-effort verification. Format differs from npm audit and across Berry
# minor versions, so this is informational only — do not gate on it yet (#122).
echo "After — yarn npm audit (informational):"
yarn npm audit --all --recursive 2>/dev/null | grep -i "$YARN_PACKAGE" || true

echo "Upgraded ${YARN_PACKAGE} (verify via CI / Dependabot)."
out fixed true
