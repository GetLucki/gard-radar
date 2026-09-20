#!/bin/zsh
# Installs (or reinstalls) the daily launchd job. Run once: zsh launchd/install.sh
set -e
SRC="${0:A:h}/com.lukizhao.gard-radar.plist"
DST="$HOME/Library/LaunchAgents/com.lukizhao.gard-radar.plist"
cp "${0:A:h}/gard-radar-run.sh" "$HOME/.claude/gard-radar-run.sh" && chmod +x "$HOME/.claude/gard-radar-run.sh"
launchctl bootout "gui/$(id -u)/com.lukizhao.gard-radar" 2>/dev/null || true
cp "$SRC" "$DST"
launchctl bootstrap "gui/$(id -u)" "$DST"
launchctl print "gui/$(id -u)/com.lukizhao.gard-radar" | grep -E 'state|program|runs' | head -5
echo "installed: runs weekly (Sat 08:00), log at ~/.claude/gard-radar.log"
