#!/usr/bin/env bash
# BLEnder yarn bump: commit yarn.lock changes via a verified commit and open a
# PR. Runs after scripts/yarn-fix.sh in the target repo checkout.
#
#   GH_TOKEN, PACKAGE, PATCHED_VERSION, ALERT_NUMBER, REPO

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/pr-lib.sh
source "${SCRIPT_DIR}/pr-lib.sh"

open_bump_pr yarn.lock
