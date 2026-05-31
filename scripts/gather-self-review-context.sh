#!/usr/bin/env bash
# BLEnder gather-self-review-context: fetch plan + merged diff, build prompt.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It writes the final prompt to .blender-prompt for run-claude.sh.
#
# Environment variables:
#   PR_NUMBER          -- Merged PR number (required)
#   ISSUE_NUMBER       -- Issue number (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN           -- GitHub token for API calls (required)
#   PROMPT_TEMPLATE    -- Path to prompt template file (required)

set -euo pipefail

if [ -z "${PR_NUMBER:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: PR_NUMBER and REPO are required."
  exit 1
fi

if [ -z "${GH_TOKEN:-}" ]; then
  echo "Error: GH_TOKEN is required."
  exit 1
fi

if [ -z "${PROMPT_TEMPLATE:-}" ]; then
  echo "Error: PROMPT_TEMPLATE is required."
  exit 1
fi

if [ ! -f "$PROMPT_TEMPLATE" ]; then
  echo "Error: Prompt template not found: $PROMPT_TEMPLATE"
  exit 1
fi

ISSUE_NUMBER="${ISSUE_NUMBER:-0}"
echo "BLEnder gather-self-review-context: PR #${PR_NUMBER} repo=${REPO}"

# --- Read plan file (BLEnder-authored, no sanitization needed) ---
plan_file=".blender/plans/${ISSUE_NUMBER}.md"
plan_content=""
if [ -f "$plan_file" ]; then
  echo "Reading plan from ${plan_file}..."
  plan_content=$(cat "$plan_file")
else
  echo "Warning: Plan file not found at ${plan_file}"
  plan_content="(plan file not found)"
fi

# --- Fetch merged PR diff ---
echo "Fetching PR #${PR_NUMBER} diff..."
pr_diff=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}" \
  -H "Accept: application/vnd.github.v3.diff" 2>/dev/null || echo "(diff unavailable)")

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

prompt="${prompt//\{\{PLAN_CONTENT\}\}/$plan_content}"
prompt="${prompt//\{\{PR_DIFF\}\}/$pr_diff}"

# Write prompt to file for run-claude.sh
echo "$prompt" > .blender-prompt
echo "Prompt written to .blender-prompt"
