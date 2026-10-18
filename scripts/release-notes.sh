#!/usr/bin/env bash
# Print the CHANGELOG.md section of one version (for example `scripts/release-notes.sh 0.1.0`),
# without its heading: the text of the GitHub release.
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:?usage: release-notes.sh <version>}"
notes=$(awk -v v="$version" '
  /^## \[/ { if (found) exit; if (index($0, "[" v "]")) { found = 1; next } }
  found { print }
' CHANGELOG.md)
if [ -z "$(printf '%s' "$notes" | tr -d '[:space:]')" ]; then
  echo "no CHANGELOG.md section for version $version" >&2
  exit 1
fi
printf '%s\n' "$notes"
