#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/skills/gtm-agent"

targets=(
  "$HOME/.agents/skills/gtm-agent"
  "$HOME/.codex/skills/gtm-agent"
  "$HOME/.gemini/antigravity/skills/gtm-agent"
  "$HOME/.claude/skills/gtm-agent"
)

for target in "${targets[@]}"; do
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ] || [ ! -e "$target" ]; then
    ln -sfn "$SOURCE" "$target"
    echo "linked $target -> $SOURCE"
  else
    echo "skip existing non-symlink: $target" >&2
  fi
done

