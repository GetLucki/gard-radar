#!/bin/zsh
# Tunn startfil för launchd. Repot ligger under ~/.claude/jobs eftersom launchd-startade
# processer inte får läsa filer under ~/Documents (macOS TCC). Symlänk finns i projektmappen.
exec /bin/zsh "$HOME/.claude/jobs/gard-radar/run_radar.sh"
