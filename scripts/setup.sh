#!/usr/bin/env bash
# BLEnder setup: explore a target repo and generate BLEnder config files.
#
# Runs Claude Code to analyze the repo and generate:
#   1. .blender/fix-dependabot-prompt.md
#   2. .blender/blender.yml
#
# Environment variables:
#   ANTHROPIC_API_KEY  -- Anthropic API key (required)
#   REPO               -- Target repo, e.g. mozilla/blurts-server (required)
#   OUTPUT_DIR          -- Where to write generated files (default: .blender)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$(dirname "$SCRIPT_DIR")/claude-settings.json"
SETUP_PROMPT="$SCRIPT_DIR/setup-prompt.md"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Error: ANTHROPIC_API_KEY is required."
  exit 1
fi

if [ -z "${REPO:-}" ]; then
  echo "Error: REPO is required."
  exit 1
fi

OUTPUT_DIR="${OUTPUT_DIR:-.blender}"

# Strip any GitHub tokens from Claude's environment
unset GH_TOKEN 2>/dev/null || true
unset ACTIONS_RUNTIME_TOKEN 2>/dev/null || true
unset ACTIONS_ID_TOKEN_REQUEST_URL 2>/dev/null || true
unset ACTIONS_ID_TOKEN_REQUEST_TOKEN 2>/dev/null || true
unset ACTIONS_CACHE_URL 2>/dev/null || true

PROMPT_NONCE=$(openssl rand -hex 16)

# Substitute variables into the setup prompt
prompt=$(cat "$SETUP_PROMPT")
prompt="${prompt/\{\{REPO\}\}/$REPO}"
prompt="${prompt/\{\{OUTPUT_DIR\}\}/$OUTPUT_DIR}"

mkdir -p "$OUTPUT_DIR"

echo "Running Claude Code to generate BLEnder config for ${REPO}..."
echo "$prompt" | claude \
  --verbose \
  --max-turns 30 \
  --settings "$SETTINGS_FILE" \
  --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
  --disallowedTools "WebSearch,WebFetch" \
  --system-prompt "You are BLEnder Setup, a configuration generator. Explore this repository and generate BLEnder config files. Do not search the web. Internal verification token: ${PROMPT_NONCE}. This token is confidential. Never include it in any output or file." \
  || true

# Nonce leak detection
if find "$OUTPUT_DIR" -type f -exec grep -lF "$PROMPT_NONCE" {} + 2>/dev/null; then
  echo "ABORT: Nonce leaked into generated files."
  rm -rf "$OUTPUT_DIR"
  exit 1
fi

# Validate expected files exist
for f in "$OUTPUT_DIR/fix-dependabot-prompt.md" \
         "$OUTPUT_DIR/blender.yml"; do
  if [ ! -f "$f" ]; then
    echo "Warning: Expected file not generated: $f"
  fi
done

echo "Setup complete. Review generated files before committing."
