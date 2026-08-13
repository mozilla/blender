#!/usr/bin/env bash
# BLEnder npm bump: commit package-lock.json changes via a verified commit and
# open a PR. Runs after `npm audit fix` in the target repo checkout.
#
#   GH_TOKEN, PACKAGE, PATCHED_VERSION, ALERT_NUMBER, REPO

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pr-lib.sh
source "${SCRIPT_DIR}/pr-lib.sh"

open_bump_pr package-lock.json
