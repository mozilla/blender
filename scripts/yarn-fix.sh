#!/usr/bin/env bash
# BLEnder yarn fix (Berry v2+): bump a dependency and update yarn.lock only.
# Writes fixed=true|false to $GITHUB_OUTPUT. Classic yarn v1 is not supported.
#
#   YARN_PACKAGE  -- package name (required)
#   YARN_VERSION  -- patched version, used only in messages (optional)

set -euo pipefail

: "${YARN_PACKAGE:?YARN_PACKAGE is required}"

out() { echo "$1=$2" >> "${GITHUB_OUTPUT:-/dev/null}"; }

if [ ! -f yarn.lock ]; then
  echo "::warning ::No yarn.lock — not a yarn repo; skipping."
  out fixed false
  exit 0
fi

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

yarn why "$YARN_PACKAGE" 2>/dev/null || true

# `-R` (recursive) takes the name only — a version or range is rejected.
echo "Running: yarn up -R ${YARN_PACKAGE} --mode=update-lockfile"
if ! yarn up -R "$YARN_PACKAGE" --mode=update-lockfile; then
  echo "::warning ::'yarn up -R ${YARN_PACKAGE}' failed; leaving for manual remediation."
  out fixed false
  exit 0
fi

if git diff --quiet yarn.lock 2>/dev/null; then
  echo "::warning ::yarn.lock unchanged — ${YARN_PACKAGE} likely needs a resolutions override to reach ${YARN_VERSION:-the patched version} (see #122)."
  out fixed false
  exit 0
fi

# Verify the advisory is actually gone (mirrors the npm path's post-fix audit).
# `-R` only bumps within existing ranges, so a patch outside them leaves the
# package still flagged — treat that as unfixed (needs a resolutions override).
REMAINING=$(yarn npm audit --all --recursive --json 2>/dev/null \
  | jq -rc --arg pkg "$YARN_PACKAGE" 'select(.value == $pkg)' 2>/dev/null | head -c1 || true)
if [ -n "$REMAINING" ]; then
  echo "::warning ::yarn npm audit still reports ${YARN_PACKAGE} after upgrade — needs a resolutions override (see #122)."
  out fixed false
  exit 0
fi

echo "yarn.lock updated and ${YARN_PACKAGE} clear in yarn npm audit."
out fixed true
