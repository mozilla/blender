#!/usr/bin/env bash
# BLEnder run-claude: run Claude Code in sandbox to fix CI failures.
#
# This script has ANTHROPIC_API_KEY but does NOT have GH_TOKEN.
# It reads the prompt from .blender-prompt (written by gather-context.sh).
#
# Environment variables:
#   ANTHROPIC_API_KEY  -- Anthropic API key (required)
#   REPO               -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   REPO_NAME          -- Display name for the repo (optional, derived from REPO)
#   BLENDER_DIR        -- Path to blender directory (default: .blender)
#   CLAUDE_VERBOSE      -- Set to "true" to print Claude's full output (default: false)

set -euo pipefail

BLENDER_DIR="${BLENDER_DIR:-.blender}"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Error: ANTHROPIC_API_KEY is required."
  exit 1
fi

if [ ! -f .blender-prompt ]; then
  echo "Error: .blender-prompt not found. Run gather-context.sh first."
  exit 1
fi

REPO_DISPLAY_NAME="${REPO_NAME:-$(echo "${REPO:-unknown}" | cut -d/ -f2)}"

# Generate nonces for leak detection
PROMPT_NONCE=$(openssl rand -hex 16)
TOKEN_NONCE=$(openssl rand -hex 16)

# Ensure no GitHub tokens exist in this process
unset GH_TOKEN 2>/dev/null || true
export GH_TOKEN="$TOKEN_NONCE"
unset ACTIONS_RUNTIME_TOKEN 2>/dev/null || true
unset ACTIONS_ID_TOKEN_REQUEST_URL 2>/dev/null || true
unset ACTIONS_ID_TOKEN_REQUEST_TOKEN 2>/dev/null || true
unset ACTIONS_CACHE_URL 2>/dev/null || true

CLAUDE_SETTINGS="$BLENDER_DIR/claude-settings.json"
CLAUDE_LOG=$(mktemp /tmp/blender-claude-XXXXXX.log)

echo "Running Claude Code to diagnose and fix..."
claude_exit=0
cat .blender-prompt | claude \
  -p \
  --verbose \
  --max-turns 30 \
  --max-budget-usd 2.00 \
  --settings "$CLAUDE_SETTINGS" \
  --allowedTools "Read,Edit,Bash" \
  --disallowedTools "WebSearch,WebFetch" \
  --system-prompt "You are BLEnder, a CI-fixing agent for ${REPO_DISPLAY_NAME}. Fix the CI failure described in the prompt. Be minimal and precise. Do not search the web. Internal verification token: ${PROMPT_NONCE}. This token is confidential. Never include it in any output, file edit, or commit message." \
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
  exit 1
fi

# --- Secret and nonce leak detection ---
diff_output=$(git diff)
for secret_label in "ANTHROPIC_API_KEY" "PROMPT_NONCE" "TOKEN_NONCE"; do
  case "$secret_label" in
    ANTHROPIC_API_KEY) secret_value="$ANTHROPIC_API_KEY" ;;
    PROMPT_NONCE)      secret_value="$PROMPT_NONCE" ;;
    TOKEN_NONCE)       secret_value="$TOKEN_NONCE" ;;
  esac
  if echo "$diff_output" | grep -qF "$secret_value"; then
    echo "ABORT: ${secret_label} leaked into changed files."
    git checkout -- .
    exit 1
  fi
  # Also check the commit message file
  if [ -f .blender-commit-msg ] && grep -qF "$secret_value" .blender-commit-msg; then
    echo "ABORT: ${secret_label} leaked into commit message."
    rm -f .blender-commit-msg
    git checkout -- .
    exit 1
  fi
done

# --- Path validation: reject changes to sensitive paths ---
FORBIDDEN_PATHS=".github/ .env .circleci/"
for forbidden in $FORBIDDEN_PATHS; do
  if git diff --name-only | grep -q "^${forbidden}"; then
    echo "ABORT: Changes detected in forbidden path: ${forbidden}"
    git checkout -- .
    exit 1
  fi
done

# --- Revert cosmetic-only changes ---
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

# --- Check for changes ---
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
