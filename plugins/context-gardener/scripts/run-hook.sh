#!/bin/sh
set -eu

SCRIPT="$PLUGIN_ROOT/skills/manage-context/scripts/context_gardener.py"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT" "$@"
fi
if command -v python >/dev/null 2>&1; then
  exec python "$SCRIPT" "$@"
fi

echo "Context Gardener requires Python 3.9 or newer; hook skipped." >&2
exit 0
