#!/usr/bin/env bash
# BLEnder parse-pr-title: extract dependency metadata from a Dependabot PR title.
#
# Reads: PR_TITLE (env var or stdin)
# Writes to $GITHUB_OUTPUT: dep_name, old_version, new_version
#
# Titles like "Bump python-ipware from 6.0.5 to 7.0.0" are parsed.
# Group titles ("Bump the eslint group...") won't match — outputs are empty.

set -euo pipefail

TITLE="${PR_TITLE:-$(cat)}"

DEP_NAME=$(echo "$TITLE" | sed -n 's/.*[Bb]ump \(.*\) from .*/\1/p')
OLD_VERSION=$(echo "$TITLE" | sed -n 's/.*from \([^ ]*\) to .*/\1/p')
NEW_VERSION=$(echo "$TITLE" | sed -n 's/.*to \([^ ]*\)/\1/p')

{
  echo "dep_name=${DEP_NAME}"
  echo "old_version=${OLD_VERSION}"
  echo "new_version=${NEW_VERSION}"
} >> "${GITHUB_OUTPUT:-/dev/null}"

echo "Parsed: ${DEP_NAME} ${OLD_VERSION} -> ${NEW_VERSION}"
