#!/usr/bin/env bash
# BLEnder gather-context: fetch PR metadata + context, build prompt.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It writes the final prompt to .blender-prompt for run-claude.sh.
#
# Always gathers: PR metadata, diff, body, release notes, CI status,
# failing checks + annotations. The prompt template determines which
# placeholders to use.
#
# Environment variables:
#   PR_NUMBER       -- PR number (required)
#   REPO            -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN        -- GitHub token for API calls (required)
#   PROMPT_TEMPLATE -- Path to prompt template file (required)
#   DEP_NAME        -- Dependency name (optional, for template substitution)
#   OLD_VERSION     -- Old version (optional, for template substitution)
#   NEW_VERSION     -- New version (optional, for template substitution)

set -euo pipefail

if [ -z "${PR_NUMBER:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: PR_NUMBER and REPO are required."
  exit 1
fi

if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Error: PR_NUMBER must be a positive integer, got: $PR_NUMBER"
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
sanitize_for_prompt() {
  local input="$1"
  # Strip HTML/XML tags (regex requires sed, not ${//})
  # shellcheck disable=SC2001
  input=$(echo "$input" | sed 's/<[^>]*>//g')
  # Strip markdown image/link injection
  # shellcheck disable=SC2001
  input=$(echo "$input" | sed 's/!\[[^]]*\]([^)]*)//g')
  # Strip prompt injection attempts
  input=$(echo "$input" | grep -viE '(ignore .* instructions|ignore .* prompt|system prompt|you are now|new instructions|disregard|forget .* above)' || true)
  echo "$input"
}

echo "BLEnder gather-context: PR #${PR_NUMBER} repo=${REPO}"

# --- Fetch PR metadata ---
echo "Fetching PR metadata..."
pr_json=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}")
pr_title=$(echo "$pr_json" | jq -r '.title')
pr_branch=$(echo "$pr_json" | jq -r '.head.ref')
pr_sha=$(echo "$pr_json" | jq -r '.head.sha')
pr_author=$(echo "$pr_json" | jq -r '.user.login')

if [ "$pr_author" != "dependabot[bot]" ]; then
  echo "Error: PR #${PR_NUMBER} is authored by '${pr_author}', not dependabot[bot]. Refusing to process."
  exit 1
fi

echo "  Title: ${pr_title}"
echo "  Branch: ${pr_branch}"
echo "  SHA: ${pr_sha}"

# --- Fetch PR diff ---
echo "Fetching PR diff..."
pr_diff=$(gh api "repos/${REPO}/pulls/${PR_NUMBER}" \
  -H "Accept: application/vnd.github.v3.diff" 2>/dev/null || echo "(diff unavailable)")

# --- Fetch PR body ---
pr_body=$(echo "$pr_json" | jq -r '.body // "(no body)"')

# --- Fetch release notes (best-effort) ---
echo "Fetching release notes..."
release_notes="(release notes unavailable)"
dep_repo_url=$(echo "$pr_body" | grep -oP 'https://github\.com/[^/]+/[^/\s)]+' | head -1 || true)
if [ -n "$dep_repo_url" ]; then
  dep_repo_path="${dep_repo_url#https://github.com/}"
  release_notes=$(gh api "repos/${dep_repo_path}/releases" \
    --jq '.[0:5] | .[] | "## \(.tag_name)\n\(.body)\n"' 2>/dev/null || echo "(release notes unavailable)")
fi

# --- Fetch CI status ---
echo "Fetching CI status..."
ci_status=""
checks_json=$(gh api "repos/${REPO}/commits/${pr_sha}/check-runs" --paginate 2>/dev/null || echo '{"check_runs":[]}')
while IFS= read -r line; do
  [ -z "$line" ] && continue
  ci_status="${ci_status}${line}
"
done < <(echo "$checks_json" | jq -r '.check_runs[] | "\(.name): \(.conclusion // .status)"')

statuses_json=$(gh api "repos/${REPO}/commits/${pr_sha}/status" 2>/dev/null || echo '{"statuses":[]}')
while IFS= read -r line; do
  [ -z "$line" ] && continue
  ci_status="${ci_status}${line}
"
done < <(echo "$statuses_json" | jq -r '.statuses[] | "\(.context): \(.state)"')

if [ -z "$ci_status" ]; then
  ci_status="No CI checks found."
fi

# --- Fetch failing checks + CI logs ---
echo "Fetching failing checks..."
failing_check_runs=$(echo "$checks_json" | jq -r '.check_runs[] | select(.conclusion == "failure") | .name')
failing_statuses=$(echo "$statuses_json" | jq -r '.statuses[] | select(.state == "failure") | .context')

failing_checks=""
if [ -n "$failing_check_runs" ]; then
  failing_checks="$failing_check_runs"
fi
if [ -n "$failing_statuses" ]; then
  if [ -n "$failing_checks" ]; then
    failing_checks="${failing_checks}
${failing_statuses}"
  else
    failing_checks="$failing_statuses"
  fi
fi

ci_logs=""
if [ -n "$failing_checks" ]; then
  echo "Failing checks:"
  echo "$failing_checks" | while read -r check; do
    echo "  - ${check}"
  done

  echo "Fetching CI logs for failing checks..."
  while IFS= read -r check_name; do
    [ -z "$check_name" ] && continue

    check_id=$(echo "$checks_json" | jq -r --arg name "$check_name" \
      '[.check_runs[] | select(.name == $name and .conclusion == "failure")] | .[0].id // empty')

    annotations=""
    if [ -n "$check_id" ] && [ "$check_id" != "null" ]; then
      annotations=$(gh api "repos/${REPO}/check-runs/${check_id}/annotations" 2>/dev/null \
        | jq -r '.[] | "  \(.path):\(.start_line): \(.annotation_level): \(.message)"' 2>/dev/null || true)
    fi

    target_url=$(echo "$statuses_json" | jq -r --arg name "$check_name" \
      '[.statuses[] | select(.context == $name and .state == "failure")] | .[0].target_url // empty')

    ci_logs="${ci_logs}

### Check: ${check_name}
"
    if [ -n "$annotations" ]; then
      ci_logs="${ci_logs}Annotations:
${annotations}
"
    elif [ -n "$target_url" ]; then
      ci_logs="${ci_logs}CircleCI URL: ${target_url}
(Log not available via API. Run the check locally to see errors.)
"
    else
      ci_logs="${ci_logs}(No log annotations available. Run the check locally to see errors.)
"
    fi
  done <<< "$failing_checks"
else
  echo "No failing checks found."
fi

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

safe_title=$(sanitize_for_prompt "$pr_title")
safe_checks=$(sanitize_for_prompt "$failing_checks")
safe_logs=$(sanitize_for_prompt "$ci_logs")
safe_diff=$(sanitize_for_prompt "$pr_diff")
safe_body=$(sanitize_for_prompt "$pr_body")
safe_notes=$(sanitize_for_prompt "$release_notes")
safe_ci=$(sanitize_for_prompt "$ci_status")

# Substitute all known placeholders — unused ones are harmless
prompt="${prompt/\{\{PR_TITLE\}\}/$safe_title}"
prompt="${prompt/\{\{FAILING_CHECKS\}\}/$safe_checks}"
prompt="${prompt/\{\{CI_LOGS\}\}/$safe_logs}"
prompt="${prompt/\{\{PR_DIFF\}\}/$safe_diff}"
prompt="${prompt/\{\{PR_BODY\}\}/$safe_body}"
prompt="${prompt/\{\{RELEASE_NOTES\}\}/$safe_notes}"
prompt="${prompt/\{\{CI_STATUS\}\}/$safe_ci}"

# Optional dep-specific placeholders (major mode)
DEP_NAME="${DEP_NAME:-}"
OLD_VERSION="${OLD_VERSION:-}"
NEW_VERSION="${NEW_VERSION:-}"
prompt="${prompt//\{\{DEP_NAME\}\}/$DEP_NAME}"
prompt="${prompt//\{\{OLD_VERSION\}\}/$OLD_VERSION}"
prompt="${prompt//\{\{NEW_VERSION\}\}/$NEW_VERSION}"

# Optional install-error placeholder (fix mode with broken installs)
install_error=""
if [ "${INSTALL_FAILED:-}" = "true" ] && [ -n "${INSTALL_LOG_FILE:-}" ] && [ -f "${INSTALL_LOG_FILE}" ]; then
  echo "Install failed — injecting last 200 lines of log into prompt."
  raw_log=$(tail -200 "$INSTALL_LOG_FILE")
  install_error=$(sanitize_for_prompt "$raw_log")
fi
prompt="${prompt//\{\{INSTALL_ERROR\}\}/$install_error}"

# Write prompt to file for run-claude.sh
echo "$prompt" > .blender-prompt

echo "Prompt written to .blender-prompt"
