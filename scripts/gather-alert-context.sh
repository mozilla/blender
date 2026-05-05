#!/usr/bin/env bash
# BLEnder gather-alert-context: fetch alert metadata, build prompt.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It writes the final prompt to .blender-prompt for run-claude.sh.
#
# Environment variables:
#   ALERT_NUMBER       -- Dependabot alert number (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN           -- GitHub token for API calls (required)
#   PROMPT_TEMPLATE    -- Path to prompt template file (required)
#   ALERT_PACKAGE      -- Package name (optional, for fallback)
#   ALERT_ECOSYSTEM    -- Ecosystem (optional, for fallback)

set -euo pipefail

if [ -z "${ALERT_NUMBER:-}" ] || [ -z "${REPO:-}" ]; then
  echo "Error: ALERT_NUMBER and REPO are required."
  exit 1
fi

if ! [[ "$ALERT_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Error: ALERT_NUMBER must be a positive integer, got: $ALERT_NUMBER"
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
  # Strip HTML/XML tags
  # shellcheck disable=SC2001
  input=$(echo "$input" | sed 's/<[^>]*>//g')
  # Strip markdown image/link injection
  # shellcheck disable=SC2001
  input=$(echo "$input" | sed 's/!\[[^]]*\]([^)]*)//g')
  # Strip prompt injection attempts
  input=$(echo "$input" | grep -viE '(ignore .* instructions|ignore .* prompt|system prompt|you are now|new instructions|disregard|forget .* above)' || true)
  echo "$input"
}

echo "BLEnder gather-alert-context: alert #${ALERT_NUMBER} repo=${REPO}"

# --- Fetch alert details ---
echo "Fetching alert details..."
alert_json=$(gh api "repos/${REPO}/dependabot/alerts/${ALERT_NUMBER}")

alert_package=$(echo "$alert_json" | jq -r '.security_vulnerability.package.name // ""')
alert_ecosystem=$(echo "$alert_json" | jq -r '.security_vulnerability.package.ecosystem // ""')
alert_severity=$(echo "$alert_json" | jq -r '.security_advisory.severity // ""')
alert_summary=$(echo "$alert_json" | jq -r '.security_advisory.summary // ""')
alert_description=$(echo "$alert_json" | jq -r '.security_advisory.description // ""')
alert_vulnerable_range=$(echo "$alert_json" | jq -r '.security_vulnerability.vulnerable_version_range // ""')
alert_patched_version=$(echo "$alert_json" | jq -r '.security_vulnerability.first_patched_version.identifier // ""')
alert_cwes=$(echo "$alert_json" | jq -r '[.security_advisory.cwes[]?.cwe_id // empty] | join(", ")')

# Use env vars as fallback if API fields are empty
alert_package="${alert_package:-${ALERT_PACKAGE:-unknown}}"
alert_ecosystem="${alert_ecosystem:-${ALERT_ECOSYSTEM:-unknown}}"

echo "  Package: ${alert_package}"
echo "  Ecosystem: ${alert_ecosystem}"
echo "  Severity: ${alert_severity}"

# --- Run ecosystem audit tool ---
echo "Running ecosystem audit..."
audit_output=""
case "$alert_ecosystem" in
  npm)
    audit_output=$(npm audit --json 2>/dev/null || echo '{"error": "npm audit failed"}')
    ;;
  pip)
    audit_output=$(pip-audit --format=json 2>/dev/null || echo '{"error": "pip-audit failed"}')
    ;;
  *)
    audit_output="(no audit tool available for ${alert_ecosystem})"
    ;;
esac

# --- Check for existing Dependabot PRs that bump this package ---
echo "Checking for existing PRs bumping ${alert_package}..."
existing_prs=$(gh api "repos/${REPO}/pulls?state=open&per_page=100" \
  --jq "[.[] | select(.user.login == \"dependabot[bot]\" and (.title | ascii_downcase | contains(\"${alert_package}\")))] | length" \
  2>/dev/null || echo "0")
echo "  Found ${existing_prs} existing PR(s) for this package."

# --- Build the prompt ---
echo "Building prompt from ${PROMPT_TEMPLATE}..."
prompt=$(cat "$PROMPT_TEMPLATE")

safe_summary=$(sanitize_for_prompt "$alert_summary")
safe_description=$(sanitize_for_prompt "$alert_description")
safe_audit=$(sanitize_for_prompt "$audit_output")

prompt="${prompt//\{\{ALERT_PACKAGE\}\}/$alert_package}"
prompt="${prompt//\{\{ALERT_ECOSYSTEM\}\}/$alert_ecosystem}"
prompt="${prompt//\{\{ALERT_SEVERITY\}\}/$alert_severity}"
prompt="${prompt//\{\{ALERT_SUMMARY\}\}/$safe_summary}"
prompt="${prompt//\{\{ALERT_DESCRIPTION\}\}/$safe_description}"
prompt="${prompt//\{\{ALERT_VULNERABLE_RANGE\}\}/$alert_vulnerable_range}"
prompt="${prompt//\{\{ALERT_PATCHED_VERSION\}\}/$alert_patched_version}"
prompt="${prompt//\{\{ALERT_CWES\}\}/$alert_cwes}"
prompt="${prompt//\{\{AUDIT_OUTPUT\}\}/$safe_audit}"

# Write prompt to file for run-claude.sh
echo "$prompt" > .blender-prompt

echo "Prompt written to .blender-prompt"
