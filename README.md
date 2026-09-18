# Gård-radar

Daily scan of Booli (primary, aggregates most broker listings) and Hemnet (best-effort, sits behind a Cloudflare check) for gårdar that match the family's criteria
(price band, land size, kommun whitelist), pre-scored deterministically,
then reviewed by Claude which writes the top-3 recommendations and sends the
daily email from litpanda. Output is published to GitHub Pages from `docs/`.

- `config.json`: budget, land minimum, kommun whitelist with region and drive time from Göteborg.
- `scanner/scan.py`: Playwright scraper. Writes `data/listings.json`, `data/changes.json`,
  `data/seen.json`, `data/digest_input.json` and `data/history/YYYY-MM-DD.json`.
- `build_site.py`: renders `docs/index.html` from the data files.
- Runner: `~/.claude/gard-radar-run.sh` (launchd `com.lukizhao.gard-radar`, daily 07:15).
- Claude prompt: `~/.claude/scheduled-tasks/daily-gard-radar/SKILL.md`.
- Criteria live in the shared Google Doc; Claude compares the doc with `config.json` daily.

Manual run:

    .venv/bin/python scanner/scan.py && python3 build_site.py

First-time setup (done by Luki, once):

    cd "$HOME/jobs/gard-radar"
    git add -A && git commit -m "first radar run" && git push -u origin main
    gh api -X POST repos/GetLucki/gard-radar/pages --field 'source[branch]=main' --field 'source[path]=/docs'
    zsh launchd/install.sh

Data sources: Booli is primary. Hemnet is tried each run and skipped if the bot check fires
(`stats.hemnet_ok` in listings.json says which). For a single Hemnet listing, open it in Chrome and
let Claude read it there.
