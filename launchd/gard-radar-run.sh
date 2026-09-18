#!/bin/zsh
# Tunn startfil för launchd. Ligger i ~/.claude eftersom launchd-startade
# processer inte får läsa filer under ~/Documents (macOS TCC) förrän de kör.
# Själva jobbet ligger i repot.
exec /bin/zsh "$HOME/Documents/Claude Code Projects/Family/Prepping/gard-radar/run_radar.sh"
