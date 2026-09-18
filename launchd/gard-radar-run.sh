#!/bin/zsh
# Tunn startfil för launchd. Repot ligger i ~/jobs/gard-radar: utanför ~/Documents
# (launchd får inte läsa där, macOS TCC) och utanför ~/.claude (Claude Code skriver inte där).
# Symlänk finns i projektmappen under Family/Prepping.
exec /bin/zsh "$HOME/jobs/gard-radar/run_radar.sh"
