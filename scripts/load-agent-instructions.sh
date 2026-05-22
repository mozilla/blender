#!/usr/bin/env bash
# Load agent instructions from .blender/ and existing repo agent files.
# Source this file from gather scripts to prepend context to prompts.
#
# Requires: sanitize.sh must be sourced first.

load_agent_instructions() {
  local instructions=""

  # Load BLEnder-specific agent instructions
  if [ -f ".blender/agents.md" ]; then
    local raw safe
    raw=$(cat .blender/agents.md)
    safe=$(sanitize_for_prompt "$raw")
    instructions="## Repository context (.blender/agents.md)\n\n${safe}\n\n"
  fi

  # Load existing repo agent instructions (first found, skip symlinks)
  for f in CLAUDE.md AGENTS.md .github/copilot-instructions.md; do
    if [ -f "$f" ] && [ ! -L "$f" ]; then
      local raw safe
      raw=$(cat "$f")
      safe=$(sanitize_for_prompt "$raw")
      instructions="${instructions}## Repository context (${f})\n\n${safe}\n\n"
      break
    fi
  done

  # Load BLEnder operational rules
  if [ -f ".blender/instructions.md" ]; then
    local raw safe
    raw=$(cat .blender/instructions.md)
    safe=$(sanitize_for_prompt "$raw")
    instructions="${instructions}## BLEnder operational rules\n\n${safe}\n\n"
  fi

  printf '%s' "$instructions"
}
