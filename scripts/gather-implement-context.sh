#!/usr/bin/env bash
# BLEnder gather-implement-context: fetch plan + issue, build implement prompt.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It writes the final prompt to .blender-prompt for run-claude.sh.
#
# Environment variables:
#   ISSUE_NUMBER       -- Issue number (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN           -- GitHub token for API calls (required)
#   PROMPT_TEMPLATE    -- Path to prompt template file (required)
#   ISSUE_TITLE        -- Issue title (optional)

set -euo pipefail

if [ -z "${ISSUE_NUMBER:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: ISSUE_NUMBER and REPO are required."
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

# --- Sanitize untrusted input before inserting into prompts ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/sanitize.sh
source "${SCRIPT_DIR}/sanitize.sh"

echo "BLEnder gather-implement-context: issue #${ISSUE_NUMBER} repo=${REPO}"

# --- Read plan file ---
plan_file=".blender/plans/${ISSUE_NUMBER}.md"
plan_content=""
if [ -f "$plan_file" ]; then
  echo "Reading plan from ${plan_file}..."
  plan_content=$(cat "$plan_file")
else
  echo "Warning: Plan file not found at ${plan_file}"
  plan_content="(plan file not found)"
fi

# --- Fetch issue body ---
echo "Fetching issue #${ISSUE_NUMBER}..."
issue_json=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}")
issue_title=$(echo "$issue_json" | jq -r '.title // ""')
issue_body=$(echo "$issue_json" | jq -r '.body // "(no body)"')

echo "  Title: ${issue_title}"

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

safe_title=$(sanitize_for_prompt "$issue_title")
safe_body=$(sanitize_for_prompt "$issue_body")
safe_plan=$(sanitize_for_prompt "$plan_content")

prompt="${prompt//\{\{ISSUE_NUMBER\}\}/$ISSUE_NUMBER}"
prompt="${prompt//\{\{ISSUE_TITLE\}\}/$safe_title}"
prompt="${prompt//\{\{ISSUE_BODY\}\}/$safe_body}"
prompt="${prompt//\{\{PLAN_CONTENT\}\}/$safe_plan}"
prompt="${prompt//\{\{REVIEW_COMMENTS\}\}/}"

# Write prompt to file for run-claude.sh
echo "$prompt" > .blender-prompt
echo "Prompt written to .blender-prompt"
