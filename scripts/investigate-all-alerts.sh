#!/usr/bin/env bash
# Trigger investigate-security-alert.yml for every open Dependabot alert
# in a target repo.
#
# Usage:
#   ./scripts/investigate-all-alerts.sh mozilla/fx-private-relay
#   ./scripts/investigate-all-alerts.sh mozilla/fx-private-relay --live
#   REF=my-branch ./scripts/investigate-all-alerts.sh mozilla/fx-private-relay
#
# By default, runs in dry-run mode. Pass --live to disable dry-run.
# Set REF to run from a specific branch (default: current branch).

set -euo pipefail

REPO="${1:?Usage: $0 <owner/repo> [--live]}"
DRY_RUN="true"
if [ "${2:-}" = "--live" ]; then
  DRY_RUN="false"
fi
REF="${REF:-$(git rev-parse --abbrev-ref HEAD)}"

WORKFLOW="investigate-security-alert.yml"

echo "Fetching open Dependabot alerts for ${REPO}..."
alerts=$(gh api "repos/${REPO}/dependabot/alerts" \
  --jq '.[] | select(.state=="open") | {
    number: .number,
    package: .security_vulnerability.package.name,
    ecosystem: .security_vulnerability.package.ecosystem,
    severity: (.security_advisory.severity // ""),
    patched: (.security_vulnerability.first_patched_version.identifier // "")
  }' | jq -s '.')

count=$(echo "$alerts" | jq 'length')
echo "Found ${count} open alert(s). dry_run=${DRY_RUN} ref=${REF}"
echo ""

if [ "$count" -eq 0 ]; then
  exit 0
fi

echo "$alerts" | jq -r '.[] | "  #\(.number) \(.package) (\(.ecosystem)) severity=\(.severity)"'
echo ""

for i in $(seq 0 $((count - 1))); do
  number=$(echo "$alerts" | jq -r ".[$i].number")
  package=$(echo "$alerts" | jq -r ".[$i].package")
  ecosystem=$(echo "$alerts" | jq -r ".[$i].ecosystem")
  severity=$(echo "$alerts" | jq -r ".[$i].severity")
  patched=$(echo "$alerts" | jq -r ".[$i].patched")

  echo "Triggering ${WORKFLOW} for alert #${number} (${package})..."
  gh workflow run "$WORKFLOW" --ref "$REF" \
    -f "target_repo=${REPO}" \
    -f "alert_number=${number}" \
    -f "alert_package=${package}" \
    -f "alert_ecosystem=${ecosystem}" \
    -f "alert_severity=${severity}" \
    -f "alert_patched_version=${patched}" \
    -f "dry_run=${DRY_RUN}"

  echo "  Triggered."
  sleep 2  # avoid hitting API rate limits
done

echo ""
echo "All ${count} investigation(s) triggered."
echo "Watch progress: https://github.com/mozilla/blender/actions/workflows/${WORKFLOW}"
