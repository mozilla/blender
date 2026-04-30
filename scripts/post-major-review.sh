#!/usr/bin/env bash
# BLEnder post-major-review: read Claude's verdict and act on it.
#
# This script has GH_TOKEN but does NOT have ANTHROPIC_API_KEY.
# It reads .blender-verdict.json written by Claude.
#
# Actions:
#   safe + high/medium confidence → approve PR, enable auto-merge, post comment
#   not safe or low confidence    → post detailed skip comment
#   no verdict file               → post fallback comment
#
# Environment variables:
#   PR_NUMBER  -- PR number (required)
#   REPO       -- GitHub repo, e.g. mozilla/fx-private-relay (required)
#   GH_TOKEN   -- GitHub token with pull-requests:write (required)
#   DRY_RUN    -- Set to "true" to skip approval/merge (default: false)

set -euo pipefail

if [ -z "${PR_NUMBER:-}" ] || [ -z "${REPO:-}" ] || [ -z "${GH_TOKEN:-}" ]; then
  echo "Error: PR_NUMBER, REPO, and GH_TOKEN are required."
  exit 1
fi

DRY_RUN="${DRY_RUN:-false}"
VERDICT_FILE=".blender-verdict.json"

# --- No verdict file: Claude failed or timed out ---
if [ ! -f "$VERDICT_FILE" ]; then
  echo "No verdict file found. Claude could not evaluate this bump."
  COMMENT="BLEnder: could not evaluate this major version bump. Manual review needed."
  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY_RUN: would comment: $COMMENT"
  else
    gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$COMMENT"
  fi
  exit 0
fi

# --- Parse verdict ---
echo "Reading verdict from $VERDICT_FILE..."
if ! jq empty "$VERDICT_FILE" 2>/dev/null; then
  echo "Error: $VERDICT_FILE is not valid JSON."
  COMMENT="BLEnder: verdict file was malformed. Manual review needed."
  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY_RUN: would comment: $COMMENT"
  else
    gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$COMMENT"
  fi
  exit 0
fi

safe=$(jq -r '.safe // false' "$VERDICT_FILE")
confidence=$(jq -r '.confidence // "low"' "$VERDICT_FILE")
reason=$(jq -r '.reason // "No reason provided"' "$VERDICT_FILE")
breaking_changes=$(jq -r '(.breaking_changes // []) | join("; ")' "$VERDICT_FILE")
affected_code=$(jq -r '(.affected_code // []) | join("; ")' "$VERDICT_FILE")
test_coverage=$(jq -r '.test_coverage // "Unknown"' "$VERDICT_FILE")

echo "Verdict: safe=$safe confidence=$confidence"
echo "Reason: $reason"

# --- Act on verdict ---
if [ "$safe" = "true" ] && [ "$confidence" != "low" ]; then
  # Safe: approve and auto-merge
  COMMENT=$(cat <<EOF
BLEnder: major version bump is safe to merge.

**Confidence:** ${confidence}
**Reason:** ${reason}

**Breaking changes:** ${breaking_changes:-None that affect this codebase}
**Test coverage:** ${test_coverage}
EOF
)

  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY_RUN: would approve and enable auto-merge"
    echo "DRY_RUN: would comment:"
    echo "$COMMENT"
  else
    echo "Approving PR and enabling auto-merge..."
    gh pr review "$PR_NUMBER" --repo "$REPO" --approve \
      --body "BLEnder auto-merge: major bump evaluated as safe (${confidence} confidence)."
    gh pr merge "$PR_NUMBER" --repo "$REPO" --auto --squash
    gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$COMMENT"
    echo "Done. PR approved and auto-merge enabled."
  fi
else
  # Not safe or low confidence: post analysis for human review
  COMMENT=$(cat <<EOF
BLEnder: this major version bump needs human review.

**Confidence:** ${confidence}
**Reason:** ${reason}

**Breaking changes:** ${breaking_changes:-None identified}
**Affected code:** ${affected_code:-None identified}
**Test coverage:** ${test_coverage}
EOF
)

  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY_RUN: would comment:"
    echo "$COMMENT"
  else
    gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$COMMENT"
    echo "Posted analysis comment for human review."
  fi
fi
