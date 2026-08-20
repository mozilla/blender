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

# Package audit state: clean | flagged | error (error = audit run failed).
pkg_audit_state() {
  local pkg="$1" out rc
  out=$(yarn npm audit --all --recursive --json 2>/dev/null)
  rc=$?
  if [ "$rc" -eq 0 ]; then echo clean; return; fi
  if [ -z "$out" ]; then echo error; return; fi
  if printf '%s\n' "$out" | jq -e --arg p "$pkg" 'select(.value == $p)' >/dev/null 2>&1; then
    echo flagged
  else
    echo clean
  fi
}

# -R takes the package name only (a version/range is rejected).
echo "Running: yarn up -R ${YARN_PACKAGE} --mode=update-lockfile"
yarn up -R "$YARN_PACKAGE" --mode=update-lockfile \
  || echo "::warning ::'yarn up -R ${YARN_PACKAGE}' failed; trying a resolution."

state=$(pkg_audit_state "$YARN_PACKAGE")
if [ "$state" = "error" ]; then
  echo "::warning ::yarn npm audit failed to run — cannot verify ${YARN_PACKAGE}; treating as unremediated."
  out fixed false
  exit 0
fi

# Out-of-range patch: fall back to a resolutions pin, single-major trees only (#122).
if [ "$state" = "flagged" ]; then
  majors=$(yarn why "$YARN_PACKAGE" --json 2>/dev/null \
    | jq -r '.children | keys[] | capture("@npm:(?<v>[0-9]+)").v' 2>/dev/null \
    | sort -u | grep -c .)
  if [ -n "${YARN_VERSION:-}" ] && [ "$majors" = "1" ]; then
    echo "In-range bump insufficient; pinning ${YARN_PACKAGE} to ${YARN_VERSION} via resolutions."
    jq --arg p "$YARN_PACKAGE" --arg v "$YARN_VERSION" \
      '.resolutions = ((.resolutions // {}) + {($p): $v})' package.json > package.json.tmp \
      && mv package.json.tmp package.json
    if ! yarn install --mode=update-lockfile; then
      echo "::warning ::yarn install failed after pinning ${YARN_PACKAGE} — treating as unremediated."
      out fixed false
      exit 0
    fi
  else
    echo "::warning ::${YARN_PACKAGE} needs a resolution but has multiple major lines (or no patched version) — manual review needed (#122)."
    out fixed false
    exit 0
  fi
fi

if [ "$(pkg_audit_state "$YARN_PACKAGE")" != "clean" ]; then
  echo "::warning ::${YARN_PACKAGE} not verified clear after remediation — manual review needed (#122)."
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
