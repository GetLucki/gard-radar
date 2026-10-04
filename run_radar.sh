#!/bin/zsh
# Daily gård-radar. Started by launchd (com.lukizhao.gard-radar) every day 07:15,
# or by hand: zsh run_radar.sh. Logs to ~/.claude/gard-radar.log when run by launchd.
#
# Steps: 1) Playwright scan of Hemnet + Booli, 2) preliminary site build,
# 3) headless Claude judges ONLY the unjudged candidates, 4) merge into the
# standing top 50, render and send the email, 5) git commit + push -> Pages.

REPO="${0:A:h}"
PROMPT_FILE="$HOME/.claude/scheduled-tasks/daily-gard-radar/SKILL.md"
SEND_FILE="$HOME/.claude/scheduled-tasks/daily-gard-radar/SEND.md"
PY="$REPO/.venv/bin/python"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
SKIP_CLAUDE="${SKIP_CLAUDE:-0}"   # SKIP_CLAUDE=1 zsh run_radar.sh  -> scan + build + publish only
SKIP_SCAN="${SKIP_SCAN:-0}"       # SKIP_SCAN=1   zsh run_radar.sh  -> judge + email + publish on existing data

ts() { date '+%F %T'; }

cd "$REPO" || { echo "$(ts) gard-radar: repo saknas: $REPO" >&2; exit 1; }
echo "$(ts) gard-radar: startar"

# 0. Vänta in nätet. Wi-Fi och routern är avstängda 23:30 till 07:00, jobbet
#    startar 07:40, och namnuppslagningen hinner inte alltid sätta sig: 3 och 4
#    oktober 2026 lyckades skanningen medan bada Claude-stegen föll pa ENOTFOUND.
#    Därför slas varje värd vi faktiskt använder upp, inte bara en webbsida.
HOSTS=(www.booli.se www.hemnet.se api.anthropic.com github.com)

resolve_ok() {
  local host
  for host in "${HOSTS[@]}"; do
    # -t 5: hellre ett snabbt nej än att hänga pa en död resolver
    if ! /usr/bin/dscacheutil -q host -a name "$host" 2>/dev/null | grep -q "ip_address"; then
      if ! /usr/bin/host -W 5 "$host" >/dev/null 2>&1; then
        LAST_BAD_HOST="$host"
        return 1
      fi
    fi
  done
  return 0
}

net_ok() {
  resolve_ok || return 1
  curl -s -m 8 -o /dev/null -w '%{http_code}' https://www.booli.se/ 2>/dev/null | grep -qE '^(2|3|4)'
}

for i in {1..72}; do
  if net_ok; then
    (( i > 1 )) && echo "$(ts) gard-radar: nätet uppe efter $(( (i - 1) * 10 )) s"
    break
  fi
  if (( i == 1 )); then
    echo "$(ts) gard-radar: väntar pa nätet (saknas: ${LAST_BAD_HOST:-okänd värd}, max 12 min)"
    # En nattlig Wi-Fi-paus lämnar ofta en inaktuell DNS-cache efter sig
    /usr/bin/dscacheutil -flushcache 2>/dev/null
    /usr/bin/sudo -n /usr/bin/killall -HUP mDNSResponder 2>/dev/null
  fi
  sleep 10
done

if ! net_ok; then
  echo "$(ts) gard-radar: inget nät efter 12 min (saknas: ${LAST_BAD_HOST:-okänd värd}), avbryter"
  echo "$(ts) inget nät efter 12 min väntan, kunde inte sla upp ${LAST_BAD_HOST:-okänd värd}" > data/scan_failed.txt
fi

# Kör ett claude -p med omförsök: ett enstaka ENOTFOUND ska inte kosta dagens mejl.
claude_try() {
  local label="$1"; shift
  local attempt out rc
  for attempt in 1 2 3; do
    out="$("$@" 2>&1)"
    rc=$?
    print -r -- "$out" | tail -n 8
    if (( rc == 0 )) && ! print -r -- "$out" | grep -qiE "API Error|ENOTFOUND|Can't reach the API server"; then
      echo "$(ts) gard-radar: $label ok (försök $attempt)"
      return 0
    fi
    echo "$(ts) gard-radar: $label misslyckades (försök $attempt, exit $rc)"
    (( attempt < 3 )) && sleep $(( attempt * 30 ))
  done
  return 1
}

# 1. scan (writes data/scan_failed.txt on crash, so Claude can report it)
if [[ "$SKIP_SCAN" != "1" ]]; then
  "$PY" scanner/scan.py 2>&1 | tail -n 40
  echo "$(ts) gard-radar: scan exit ${pipestatus[1]}"
fi

# 2. preliminary build so the site is fresh even if Claude fails
python3 build_site.py

# 3. Claude, step one: judge ONLY the listings nobody has judged yet
JUDGED=0
if [[ "$SKIP_CLAUDE" != "1" ]]; then
  CLAUDE=""
  for cand in /opt/homebrew/bin/claude "$HOME"/.nvm/versions/node/*/bin/claude(N-.om); do
    [[ -x "$cand" ]] && { CLAUDE="$cand"; break; }
  done
  if [[ -z "$CLAUDE" ]]; then
    echo "$(ts) gard-radar: ingen claude-binär hittad" >&2
  else
    PROMPT="$(awk 'NR==1 && $0=="---" {infm=1; next} infm && $0=="---" {infm=0; next} !infm' "$PROMPT_FILE")"
    if [[ -n "$PROMPT" ]]; then
      rm -f data/new_judgements.json
      claude_try judge "$CLAUDE" -p "$PROMPT" \
        --permission-mode acceptEdits \
        --add-dir "$HOME/.claude" --add-dir "$REPO" \
        --allowedTools "Read,Write,Edit,Glob,Grep,\
Bash(date:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),\
mcp__gsuite-kalender-privat__read_file,\
mcp__gmail-litpanda-auto__send_message"
      [[ -f data/new_judgements.json ]] && JUDGED=1
    fi
  fi
fi

# 4. merge the judgements into the standing top 50 and render the email
python3 merge_board.py
python3 build_email.py | tail -n 2
python3 build_site.py

# 4b. Claude, step two: send the rendered email (only the MCP tool can send)
if [[ "$SKIP_CLAUDE" != "1" && -s data/email.html ]]; then
  SEND_PROMPT="$(awk 'NR==1 && $0=="---" {infm=1; next} infm && $0=="---" {infm=0; next} !infm' "$SEND_FILE")"
  if [[ -n "$SEND_PROMPT" && -n "$CLAUDE" ]]; then
    claude_try send "$CLAUDE" -p "$SEND_PROMPT" \
      --permission-mode acceptEdits \
      --add-dir "$REPO" \
      --allowedTools "Read,Glob,Grep,mcp__gmail-litpanda-auto__send_message"
  fi
fi

# 5. publish
git add -A
if git diff --cached --quiet; then
  echo "$(ts) gard-radar: inga ändringar att publicera"
else
  git commit -q -m "radar $(date +%F)" && git push -q origin HEAD && echo "$(ts) gard-radar: publicerad"
fi
echo "$(ts) gard-radar: klar"
