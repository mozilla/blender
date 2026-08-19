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

# Is the package still flagged by audit? (empty output = clear)
audit_flagged() {
  yarn npm audit --all --recursive --json 2>/dev/null \
    | jq -rc --arg pkg "$1" 'select(.value == $pkg)' 2>/dev/null | head -c1 || true
}

# `-R` (recursive) takes the name only — a version/range is rejected. It bumps
# every occurrence to the newest version each existing range allows.
echo "Running: yarn up -R ${YARN_PACKAGE} --mode=update-lockfile"
yarn up -R "$YARN_PACKAGE" --mode=update-lockfile \
  || echo "::warning ::'yarn up -R ${YARN_PACKAGE}' failed; trying a resolution."

# If the in-range bump didn't clear the advisory, the patch is out of some
# consumer's range. Fall back to a resolutions override — but only for a
# single-major tree: a global resolution across majors would break the other
# majors, and scoped resolutions can't be matched reliably (see #122).
if [ -n "$(audit_flagged "$YARN_PACKAGE")" ]; then
  majors=$(grep -A1 "^\"${YARN_PACKAGE}@" yarn.lock 2>/dev/null \
    | sed -nE 's/^ *version: "?([0-9]+).*/\1/p' | sort -u | grep -c .)
  if [ -n "${YARN_VERSION:-}" ] && [ "$majors" = "1" ]; then
    echo "In-range bump insufficient; pinning ${YARN_PACKAGE} to ${YARN_VERSION} via resolutions."
    jq --arg p "$YARN_PACKAGE" --arg v "$YARN_VERSION" \
      '.resolutions = ((.resolutions // {}) + {($p): $v})' package.json > package.json.tmp \
      && mv package.json.tmp package.json
    yarn install --mode=update-lockfile || true
  else
    echo "::warning ::${YARN_PACKAGE} needs a resolution but has multiple major lines (or no patched version) — manual review needed (#122)."
    out fixed false
    exit 0
  fi
fi

# Final check: advisory gone, and something actually changed to open a PR from.
if [ -n "$(audit_flagged "$YARN_PACKAGE")" ]; then
  echo "::warning ::${YARN_PACKAGE} still flagged after remediation — manual review needed (#122)."
  out fixed false
  exit 0
fi
if git diff --quiet yarn.lock package.json 2>/dev/null; then
  echo "::warning ::no changes produced for ${YARN_PACKAGE}; nothing to open."
  out fixed false
  exit 0
fi

echo "${YARN_PACKAGE} cleared in yarn npm audit."
out fixed true
