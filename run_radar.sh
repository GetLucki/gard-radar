#!/bin/zsh
# Daily gård-radar. Started by launchd (com.lukizhao.gard-radar) every day 07:15,
# or by hand: zsh run_radar.sh. Logs to ~/.claude/gard-radar.log when run by launchd.
#
# Steps: 1) Playwright scan of Hemnet + Booli, 2) preliminary site build,
# 3) headless Claude judges candidates + sends the litpanda email,
# 4) final site build, 5) git commit + push -> GitHub Pages.

REPO="${0:A:h}"
PROMPT_FILE="$HOME/.claude/scheduled-tasks/daily-gard-radar/SKILL.md"
PY="$REPO/.venv/bin/python"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
SKIP_CLAUDE="${SKIP_CLAUDE:-0}"   # SKIP_CLAUDE=1 zsh run_radar.sh  -> scan + build + publish only
SKIP_SCAN="${SKIP_SCAN:-0}"       # SKIP_SCAN=1   zsh run_radar.sh  -> judge + email + publish on existing data

ts() { date '+%F %T'; }

cd "$REPO" || { echo "$(ts) gard-radar: repo saknas: $REPO" >&2; exit 1; }
echo "$(ts) gard-radar: startar"

# 1. scan (writes data/scan_failed.txt on crash, so Claude can report it)
if [[ "$SKIP_SCAN" != "1" ]]; then
  "$PY" scanner/scan.py 2>&1 | tail -n 40
  echo "$(ts) gard-radar: scan exit ${pipestatus[1]}"
fi

# 2. preliminary build so the site is fresh even if Claude fails
python3 build_site.py

# 3. Claude: read doc, judge, write recommendations, send email
if [[ "$SKIP_CLAUDE" != "1" ]]; then
  # Prefer the Homebrew binary (kept current by brew); the nvm copy lags and
  # rejected the Fable 5.1 default model on 2026-09-17.
  CLAUDE=""
  for cand in /opt/homebrew/bin/claude "$HOME"/.nvm/versions/node/*/bin/claude(N-.om); do
    [[ -x "$cand" ]] && { CLAUDE="$cand"; break; }
  done
  if [[ -z "$CLAUDE" ]]; then
    echo "$(ts) gard-radar: ingen claude-binär hittad" >&2
  else
    PROMPT="$(awk 'NR==1 && $0=="---" {infm=1; next} infm && $0=="---" {infm=0; next} !infm' "$PROMPT_FILE")"
    if [[ -z "$PROMPT" ]]; then
      echo "$(ts) gard-radar: prompten blev tom" >&2
    else
      "$CLAUDE" -p "$PROMPT" \
        --permission-mode acceptEdits \
        --add-dir "$HOME/.claude" --add-dir "$REPO" \
        --allowedTools "Read,Write,Edit,Glob,Grep,\
Bash(date:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),\
Bash(python3 \"$REPO/build_email.py\"),Bash(python3 $REPO/build_email.py),\
mcp__gsuite-kalender-privat__read_file,\
mcp__gmail-litpanda-auto__send_message" 2>&1 | tail -n 20
      echo "$(ts) gard-radar: claude exit ${pipestatus[1]}"
    fi
  fi
fi

# 4. final build with recommendations
python3 build_site.py

# 5. publish
git add -A
if git diff --cached --quiet; then
  echo "$(ts) gard-radar: inga ändringar att publicera"
else
  git commit -q -m "radar $(date +%F)" && git push -q origin HEAD && echo "$(ts) gard-radar: publicerad"
fi
echo "$(ts) gard-radar: klar"
