#!/usr/bin/env python3
"""Render the daily email (HTML + plain text) from data/recommendations.json,
data/listings.json and data/changes.json. Fixed layout so every morning looks
the same; Claude only supplies the judgement in recommendations.json.

Writes data/email.html and data/email.txt and prints the subject line.
"""
import datetime
import html
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
CFG = json.load(open(ROOT / "config.json", encoding="utf-8"))


def load(name, default):
    try:
        return json.load(open(DATA / name, encoding="utf-8"))
    except Exception:
        return default


R = load("recommendations.json", {})
L = load("listings.json", {"stats": {}, "listings": []})
C = load("changes.json", {"new": [], "gone": [], "price_changes": []})
S = L.get("stats", {})
by_id = {}
for _l in L.get("listings", []):
    by_id[_l["id"]] = _l
    for _a in _l.get("alt_ids", []):
        by_id[_a] = _l
date = R.get("date") or S.get("date") or datetime.date.today().isoformat()
site = CFG["site_url"]
doc = CFG["doc_url"]

def kr(n):
    return "–" if n is None else f"{int(n):,}".replace(",", " ") + " kr"

def e(s):
    return html.escape(str(s if s is not None else ""))

picks = R.get("top", R.get("top3", []))
n_cuts = S.get("price_cuts", 0)
subject = f"Gård-radar {date}: {S.get('matched', '?')} matching, {S.get('new', '?')} new, {n_cuts} price cuts"

# ---------- criteria box (what the judgement is based on) ----------
criteria_surv = [
    "Own water: drilled well plus lake or stream on the land",
    "Land: 3 to 30 ha, forest for firewood, some arable or pasture",
    "Low-maintenance house: brick or rendered facade, metal or concrete-tile roof, replaced windows, built 1965 or later or totally renovated",
    "Wood heating installed, secluded access, under 2.5 h from Göteborg",
]
criteria_fin = [
    "Southern forest price tier (930 kr per m3sk, near all-time high, H1 2026)",
    "County with a positive 5-year price trend (Kronoberg, Halland, Kalmar inland, Värmland, VG inland)",
    "Asking price per hectare below the median of all matching listings",
    "Liquid local market and a tourism draw within 30 minutes, so it resells",
]

# ---------- HTML ----------
css = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;color:#1f2a1f;line-height:1.45;margin:0;padding:0;background:#f6f4ee}
.wrap{max-width:900px;margin:0 auto;padding:18px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:22px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}
.sub{color:#666;margin-bottom:12px}
.kpis td{padding:8px 12px;background:#fff;border:1px solid #e3e0d6;border-radius:8px;text-align:center}
.kpis b{font-size:20px;display:block}
.crit{display:table;width:100%}.crit td{vertical-align:top;width:50%;padding:0 8px 0 0}
ul{margin:4px 0 0 18px;padding:0}li{margin:2px 0}
table.t{border-collapse:collapse;width:100%;background:#fff;table-layout:fixed}
table.t th{background:#2f6b3a;color:#fff;text-align:left;padding:8px;font-size:12px;vertical-align:top}
table.t td{border-bottom:1px solid #e3e0d6;padding:8px;vertical-align:top;font-size:13px}
table.t tr:nth-child(even) td{background:#fafaf7}
.rank{font-size:20px;font-weight:700;color:#2f6b3a;text-align:center}
.rec{font-weight:700}.rec.go{color:#2f6b3a}.rec.watch{color:#b5541c}.rec.skip{color:#888}
.small{font-size:12px;color:#666}
a{color:#2f6b3a}
"""

def rec_class(txt):
    t = (txt or "").lower()
    if any(w in t for w in ("book", "viewing", "visning", "bid", "go")):
        return "go"
    if any(w in t for w in ("watch", "wait", "ask", "hold")):
        return "watch"
    return "skip"

rows = []
for i, p in enumerate(picks, 1):
    l = by_id.get(p.get("id"), {})
    title = p.get("title") or l.get("title", "")
    url = p.get("url") or l.get("url", "")
    facts = " · ".join(x for x in [
        f"{e(p.get('kommun') or l.get('kommun'))} ({e(l.get('region', ''))})",
        kr(p.get("price") or l.get("price")),
        f"{p.get('land_ha') or l.get('land_ha') or '?'} ha",
        f"{l.get('living_m2')} m²" if l.get("living_m2") else "",
        f"byggår {l.get('build_year')}" if l.get("build_year") else "",
        f"{l.get('drive_h')} h from Göteborg" if l.get("drive_h") else "",
        f"score {p.get('score') or l.get('score')}",
    ] if x)
    rows.append(f"""
<tr>
 <td class="rank">{i}</td>
 <td><a href="{e(url)}"><b>{e(title)}</b></a><br><span class="small">{facts}</span>
     {('<br><span class="small"><b>Maintenance:</b> ' + e(p.get('maintenance')) + '</span>') if p.get('maintenance') else ''}</td>
 <td>{e(p.get('prepping_why') or p.get('why'))}</td>
 <td>{e(p.get('invest_why'))}</td>
 <td>{e(p.get('rank_why'))}</td>
 <td class="rec {rec_class(p.get('recommendation'))}">{e(p.get('recommendation'))}</td>
</tr>""")

changes_html = ""
if C.get("first_run"):
    changes_html = "<p>First run: everything counts as new.</p>"
else:
    items = []
    for x in (C.get("new") or [])[:10]:
        items.append(f"<li><b>New</b>: <a href=\"{e(x['url'])}\">{e(x['title'])}</a>, {e(x['kommun'])}, {kr(x['price'])}, score {x.get('score')}</li>")
    for x in (C.get("price_changes") or [])[:10]:
        arrow = "cut" if x["new"] < x["old"] else "up"
        items.append(f"<li><b>Price {arrow}</b>: <a href=\"{e(x['url'])}\">{e(x['title'])}</a>, {kr(x['old'])} to {kr(x['new'])}</li>")
    for x in (C.get("gone") or [])[:10]:
        items.append(f"<li><b>Gone</b>: {e(x.get('title'))}, {e(x.get('kommun'))}, {kr(x.get('price'))}</li>")
    changes_html = "<ul>" + "".join(items) + "</ul>" if items else "<p>No changes since yesterday.</p>"

dropped_html = ""
if R.get("dropped"):
    dropped_html = "<p class=\"small\"><b>Left the list:</b> " + "; ".join(f"{e(d.get('title'))} ({e(d.get('why'))})" for d in R["dropped"]) + "</p>"
crit_changes_html = ""
if R.get("criteria_changes"):
    crit_changes_html = "<p class=\"small\"><b>Criteria updated from the plan doc:</b> " + "; ".join(e(x) for x in R["criteria_changes"]) + "</p>"

region_rows = "".join(
    f"<tr><td>{e(k)}</td><td>{v['count']}</td><td>{v.get('new', 0)}</td><td>{kr(v.get('median_price'))}</td></tr>"
    for k, v in sorted((S.get("by_region") or {}).items(), key=lambda kv: -kv[1]["count"]))

html_out = f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="wrap">
<h1>Gård-radar {e(date)}</h1>
<div class="sub">{S.get('matched', '?')} matching listings · {S.get('new', 0)} new · {S.get('gone', 0)} gone · {n_cuts} price cuts · median asking {kr(S.get('median_price'))} · median {kr(S.get('median_price_per_ha'))} per ha</div>

<h2>In one paragraph</h2>
<p>{e(R.get('market_summary') or 'No judgement written today.')}</p>

<h2>Today's picks</h2>
<table class="t">
<tr><th style="width:3%">#</th><th style="width:19%">Property</th><th style="width:26%">Why it works for survival</th><th style="width:24%">Why it works as an investment</th><th style="width:15%">Why this rank</th><th style="width:13%">Recommendation</th></tr>
{''.join(rows) if rows else '<tr><td colspan="6">No listing passed the bar today.</td></tr>'}
</table>
{dropped_html}
{crit_changes_html}

<h2>What the picks are judged on</h2>
<div class="crit"><table width="100%"><tr>
<td><b>Survival</b><ul>{''.join(f'<li>{e(x)}</li>' for x in criteria_surv)}</ul></td>
<td><b>Financial</b><ul>{''.join(f'<li>{e(x)}</li>' for x in criteria_fin)}</ul></td>
</tr></table></div>
<p class="small">Full criteria and weights: <a href="{e(doc)}">plan document</a>, section 6 and 8. Edit the doc and tomorrow's run follows.</p>

<h2>Market by region</h2>
<table class="t"><tr><th>Region</th><th>Listings</th><th>New</th><th>Median asking</th></tr>{region_rows}</table>

<h2>Changes since yesterday</h2>
{changes_html}

<p><a href="{e(site)}"><b>Open the full radar site</b></a> (all {S.get('matched', '?')} listings, filters, scores) · <a href="{e(doc)}">Plan document</a></p>
<p class="small">Sources: Hemnet and Booli, scanned {e(L.get('generated', ''))}. Scores are a keyword pre-score; the picks and reasons are Claude's daily judgement. Verify everything at a viewing.</p>
</div></body></html>"""

# ---------- plain text fallback ----------
lines = [f"GÅRD-RADAR {date}", subject.split(': ', 1)[1] if ': ' in subject else "", "",
         "IN ONE PARAGRAPH", R.get("market_summary") or "No judgement written today.", "", "TODAY'S PICKS"]
for i, p in enumerate(picks, 1):
    l = by_id.get(p.get("id"), {})
    lines += [f"{i}. {p.get('title') or l.get('title')}, {p.get('kommun') or l.get('kommun')}, {kr(p.get('price') or l.get('price'))}, {p.get('land_ha') or l.get('land_ha') or '?'} ha",
              f"   Survival: {p.get('prepping_why') or p.get('why') or ''}",
              f"   Investment: {p.get('invest_why') or ''}",
              f"   Why this rank: {p.get('rank_why') or ''}",
              f"   Maintenance: {p.get('maintenance') or ''}",
              f"   Recommendation: {p.get('recommendation') or ''}",
              f"   {p.get('url') or l.get('url') or ''}", ""]
if R.get("dropped"):
    lines += ["Left the list: " + "; ".join(f"{d.get('title')} ({d.get('why')})" for d in R["dropped"]), ""]
lines += ["JUDGED ON", "Survival: " + "; ".join(criteria_surv), "Financial: " + "; ".join(criteria_fin), "",
          "CHANGES", f"New {S.get('new', 0)}, gone {S.get('gone', 0)}, price cuts {n_cuts}.", "",
          f"Site: {site}", f"Plan doc: {doc}"]
text_out = "\n".join(lines)

(DATA / "email.html").write_text(html_out, encoding="utf-8")
(DATA / "email.txt").write_text(text_out, encoding="utf-8")
print(subject)
print(f"html {len(html_out)} chars -> {DATA/'email.html'}; text {len(text_out)} chars -> {DATA/'email.txt'}")
