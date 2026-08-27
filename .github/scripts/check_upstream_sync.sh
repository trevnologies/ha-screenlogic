#!/usr/bin/env bash
# Checks whether home-assistant/core's built-in screenlogic component has
# changed since our last recorded snapshot, and writes a human-readable
# report. Does NOT auto-merge anything -- this integration diverges from
# core too heavily in several files (coordinator.py, config_flow.py,
# number.py, sensor.py, light.py, entity.py) for a blind merge to be safe.
# This only tells you *that* and *what* changed upstream so you can decide
# what to pull forward by hand.
set -euo pipefail

SNAPSHOT_DIR=".upstream-snapshot/screenlogic"
REPORT_FILE="upstream-sync-report.md"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "Cloning home-assistant/core (sparse: screenlogic component only)..."
git clone --filter=blob:none --no-checkout --depth 1 \
  https://github.com/home-assistant/core.git "$WORKDIR/core" --quiet
(
  cd "$WORKDIR/core"
  git sparse-checkout init --cone
  git sparse-checkout set homeassistant/components/screenlogic
  git checkout dev --quiet
)

UPSTREAM_DIR="$WORKDIR/core/homeassistant/components/screenlogic"

if [ ! -d "$SNAPSHOT_DIR" ]; then
  echo "No existing snapshot found at $SNAPSHOT_DIR -- treating this run as the baseline."
  mkdir -p "$(dirname "$SNAPSHOT_DIR")"
  cp -r "$UPSTREAM_DIR" "$SNAPSHOT_DIR"
  echo "changed=0" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

CHANGED=0
{
  echo "# Upstream ScreenLogic sync report"
  echo
  echo "Comparing \`home-assistant/core\` (\`dev\` branch,"\
       "\`homeassistant/components/screenlogic\`) against the snapshot"\
       "last recorded in this repo."
  echo
} > "$REPORT_FILE"

# Files present upstream now but never seen in our snapshot at all --
# i.e. core added a whole new file since we last looked.
NEW_FILES=$(comm -13 \
  <(cd "$SNAPSHOT_DIR" && find . -type f | sed 's|^\./||' | sort) \
  <(cd "$UPSTREAM_DIR" && find . -type f | sed 's|^\./||' | sort) || true)

if [ -n "$NEW_FILES" ]; then
  CHANGED=1
  echo "## New files added upstream" >> "$REPORT_FILE"
  echo "These don't exist in our snapshot at all -- check whether core added" >> "$REPORT_FILE"
  echo "a new platform/feature we don't have:" >> "$REPORT_FILE"
  echo >> "$REPORT_FILE"
  while IFS= read -r f; do
    echo "- \`$f\`" >> "$REPORT_FILE"
  done <<< "$NEW_FILES"
  echo >> "$REPORT_FILE"
fi

# Files that exist in both but differ
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if [ -f "$SNAPSHOT_DIR/$f" ]; then
    if ! diff -q "$SNAPSHOT_DIR/$f" "$UPSTREAM_DIR/$f" > /dev/null 2>&1; then
      CHANGED=1
      {
        echo "## Changed: \`$f\`"
        echo '```diff'
        diff -u "$SNAPSHOT_DIR/$f" "$UPSTREAM_DIR/$f" || true
        echo '```'
        echo
      } >> "$REPORT_FILE"
    fi
  fi
done < <(cd "$UPSTREAM_DIR" && find . -type f | sed 's|^\./||' | sort)

if [ "$CHANGED" -eq 0 ]; then
  echo "No changes detected upstream since the last snapshot." >> "$REPORT_FILE"
fi

echo "changed=$CHANGED" >> "${GITHUB_OUTPUT:-/dev/null}"

# Always refresh the snapshot so the next run diffs from *this* point
# forward, not cumulatively from whenever the snapshot was first made.
rm -rf "$SNAPSHOT_DIR"
mkdir -p "$(dirname "$SNAPSHOT_DIR")"
cp -r "$UPSTREAM_DIR" "$SNAPSHOT_DIR"

cat "$REPORT_FILE"