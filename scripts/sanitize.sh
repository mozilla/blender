#!/usr/bin/env bash
# Shared sanitization for untrusted input before inserting into prompts.
# Source this file from scripts that build prompts.

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
