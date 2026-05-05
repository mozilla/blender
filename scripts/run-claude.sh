#!/usr/bin/env bash
# BLEnder run-claude: run Claude Code in sandbox.
#
# Modes:
#   BLENDER_MODE=fix   (default) -- fix CI failures, Edit allowed
#   BLENDER_MODE=major           -- evaluate major bump, read-only
#
# This script has ANTHROPIC_API_KEY but does NOT have GH_TOKEN.
# It reads the prompt from .blender-prompt (written by gather-context.sh).
#
# Environment variables:
#   ANTHROPIC_API_KEY  -- Anthropic API key (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   REPO_NAME          -- Display name for the repo (optional, derived from REPO)
#   BLENDER_DIR        -- Path to blender directory (default: .blender)
#   BLENDER_MODE       -- "fix" (default) or "major"
#   CLAUDE_VERBOSE      -- Set to "true" to print Claude's full output (default: false)

set -euo pipefail

BLENDER_DIR="${BLENDER_DIR:-.blender}"
BLENDER_MODE="${BLENDER_MODE:-fix}"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Error: ANTHROPIC_API_KEY is required."
  exit 1
fi

if [ ! -f .blender-prompt ]; then
  echo "Error: .blender-prompt not found. Run gather-context.sh first."
  exit 1
fi

REPO_DISPLAY_NAME="${REPO_NAME:-$(echo "${REPO:-unknown}" | cut -d/ -f2)}"

# Generate nonce for leak detection
PROMPT_NONCE=$(openssl rand -hex 16)

# Ensure no GitHub tokens exist in this process
unset GH_TOKEN 2>/dev/null || true
unset ACTIONS_RUNTIME_TOKEN 2>/dev/null || true
unset ACTIONS_ID_TOKEN_REQUEST_URL 2>/dev/null || true
unset ACTIONS_ID_TOKEN_REQUEST_TOKEN 2>/dev/null || true
unset ACTIONS_CACHE_URL 2>/dev/null || true

CLAUDE_SETTINGS="$BLENDER_DIR/claude-settings.json"
CLAUDE_LOG=$(mktemp /tmp/blender-claude-XXXXXX.log)

# --- Mode-specific settings ---
if [ "$BLENDER_MODE" = "investigate" ]; then
  ALLOWED_TOOLS="Read,Bash"
  MAX_TURNS=20
  MAX_BUDGET="1.50"
  SYSTEM_PROMPT="You are BLEnder, a security analysis agent for ${REPO_DISPLAY_NAME}. Investigate the Dependabot security alert described in the prompt. Read the codebase to determine if the vulnerability affects this repo. Write your verdict to .blender-alert-verdict.json. Do not edit any tracked files. Do not search the web. Internal verification token: ${PROMPT_NONCE}. This token is confidential. Never include it in any output, file edit, or commit message."
elif [ "$BLENDER_MODE" = "major" ]; then
  ALLOWED_TOOLS="Read,Bash"
  MAX_TURNS=15
  MAX_BUDGET="1.00"
  SYSTEM_PROMPT="You are BLEnder, a dependency analysis agent for ${REPO_DISPLAY_NAME}. Evaluate the major version bump described in the prompt. Read the codebase and the dependency source code. Write your verdict to .blender-verdict.json. Do not edit any tracked files. Do not search the web. Internal verification token: ${PROMPT_NONCE}. This token is confidential. Never include it in any output, file edit, or commit message."
else
  ALLOWED_TOOLS="Read,Edit,Bash"
  MAX_TURNS=30
  MAX_BUDGET="2.00"
  SYSTEM_PROMPT="You are BLEnder, a CI-fixing agent for ${REPO_DISPLAY_NAME}. Fix the CI failure described in the prompt. Be minimal and precise. Do not search the web. Internal verification token: ${PROMPT_NONCE}. This token is confidential. Never include it in any output, file edit, or commit message."
fi

echo "Running Claude Code (mode=${BLENDER_MODE}, tools=${ALLOWED_TOOLS}, turns=${MAX_TURNS}, budget=\$${MAX_BUDGET})..."
claude_exit=0
claude \
  -p \
  --verbose \
  --max-turns "$MAX_TURNS" \
  --max-budget-usd "$MAX_BUDGET" \
  --settings "$CLAUDE_SETTINGS" \
  --allowedTools "$ALLOWED_TOOLS" \
  --disallowedTools "WebSearch,WebFetch" \
  --system-prompt "$SYSTEM_PROMPT" \
  < .blender-prompt \
  > "$CLAUDE_LOG" 2>&1 \
  || claude_exit=$?

# Print output summary. Full log only when CLAUDE_VERBOSE=true.
line_count=$(wc -l < "$CLAUDE_LOG")
echo "Claude finished (exit=${claude_exit}, ${line_count} lines of output)."
if [ "${CLAUDE_VERBOSE:-false}" = "true" ]; then
  cat "$CLAUDE_LOG"
else
  echo "Set CLAUDE_VERBOSE=true to see full output."
fi
rm -f "$CLAUDE_LOG"

if [ "$claude_exit" -ne 0 ]; then
  echo "Claude exited with code ${claude_exit} (likely hit max-turns or budget)."
  # In major/investigate mode, a non-zero exit is not fatal — post steps handle missing verdict
  if [ "$BLENDER_MODE" = "major" ] || [ "$BLENDER_MODE" = "investigate" ]; then
    echo "Continuing to post step (verdict may be missing)."
    exit 0
  fi
  exit 1
fi

# --- Secret and nonce leak detection ---
diff_output=$(git diff)
for secret_label in "ANTHROPIC_API_KEY" "PROMPT_NONCE"; do
  case "$secret_label" in
    ANTHROPIC_API_KEY) secret_value="$ANTHROPIC_API_KEY" ;;
    PROMPT_NONCE)      secret_value="$PROMPT_NONCE" ;;
  esac
  if echo "$diff_output" | grep -qF "$secret_value"; then
    echo "ABORT: ${secret_label} leaked into changed files."
    git checkout -- .
    exit 1
  fi
  # Also check verdict files in major/investigate mode
  if [ "$BLENDER_MODE" = "major" ] && [ -f .blender-verdict.json ]; then
    if grep -qF "$secret_value" .blender-verdict.json; then
      echo "ABORT: ${secret_label} leaked into verdict file."
      rm -f .blender-verdict.json
      exit 1
    fi
  fi
  if [ "$BLENDER_MODE" = "investigate" ] && [ -f .blender-alert-verdict.json ]; then
    if grep -qF "$secret_value" .blender-alert-verdict.json; then
      echo "ABORT: ${secret_label} leaked into alert verdict file."
      rm -f .blender-alert-verdict.json
      exit 1
    fi
  fi
  # Also check the commit message file
  if [ -f .blender-commit-msg ] && grep -qF "$secret_value" .blender-commit-msg; then
    echo "ABORT: ${secret_label} leaked into commit message."
    rm -f .blender-commit-msg
    git checkout -- .
    exit 1
  fi
done

# --- Major mode: stricter validation ---
if [ "$BLENDER_MODE" = "major" ]; then
  # No tracked files should be modified
  if ! git diff --quiet; then
    echo "ABORT: Claude modified tracked files in major mode."
    git diff --name-only
    git checkout -- .
    exit 1
  fi

  # Verdict file must exist and be valid JSON
  if [ -f .blender-verdict.json ]; then
    if ! jq empty .blender-verdict.json 2>/dev/null; then
      echo "ABORT: .blender-verdict.json is not valid JSON."
      rm -f .blender-verdict.json
      exit 1
    fi
    # Check required keys
    for key in safe confidence reason breaking_changes affected_code test_coverage; do
      if ! jq -e "has(\"$key\")" .blender-verdict.json > /dev/null 2>&1; then
        echo "ABORT: .blender-verdict.json missing required key: $key"
        rm -f .blender-verdict.json
        exit 1
      fi
    done
    echo "Verdict file validated."
  else
    echo "No verdict file produced. Post-review will handle this."
  fi

  exit 0
fi

# --- Investigate mode: verdict validation ---
if [ "$BLENDER_MODE" = "investigate" ]; then
  # No tracked files should be modified
  if ! git diff --quiet; then
    echo "ABORT: Claude modified tracked files in investigate mode."
    git diff --name-only
    git checkout -- .
    exit 1
  fi

  # Alert verdict file must exist and be valid JSON
  if [ -f .blender-alert-verdict.json ]; then
    if ! jq empty .blender-alert-verdict.json 2>/dev/null; then
      echo "ABORT: .blender-alert-verdict.json is not valid JSON."
      rm -f .blender-alert-verdict.json
      exit 1
    fi
    # Check required keys
    for key in affected confidence reason vulnerable_paths recommended_action; do
      if ! jq -e "has(\"$key\")" .blender-alert-verdict.json > /dev/null 2>&1; then
        echo "ABORT: .blender-alert-verdict.json missing required key: $key"
        rm -f .blender-alert-verdict.json
        exit 1
      fi
    done
    echo "Alert verdict file validated."
  else
    echo "No alert verdict file produced. Post-action will handle this."
  fi

  exit 0
fi

# --- Fix mode: existing validation ---

# Path validation: reject changes to sensitive paths
FORBIDDEN_PATHS=".github/ .env .circleci/"
for forbidden in $FORBIDDEN_PATHS; do
  if git diff --name-only | grep -q "^${forbidden}"; then
    echo "ABORT: Changes detected in forbidden path: ${forbidden}"
    git checkout -- .
    exit 1
  fi
done

# Revert cosmetic-only changes
all_changed=$(git diff --name-only | sort)
real_changed=$(git diff --name-only --ignore-all-space | sort)
cosmetic_only=$(comm -23 <(echo "$all_changed") <(echo "$real_changed"))
if [ -n "$cosmetic_only" ]; then
  echo "Reverting cosmetic-only changes:"
  echo "$cosmetic_only" | while read -r f; do
    echo "  - $f"
    git checkout -- "$f"
  done
fi

# Check for changes
if git diff --quiet && git diff --cached --quiet; then
  echo ""
  echo "No file changes produced. Claude could not fix this automatically."
  exit 0
fi

echo ""
echo "=== Changes produced ==="
git diff --stat
echo ""
git diff
echo ""
