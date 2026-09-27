#!/usr/bin/env python3
"""Render the daily email (HTML + plain text) from the standing board.

Layout (Luki, 2026-09-27): the board is a standing top 50 that changes slowly.
What entered in the latest run comes first, in full, marked NEW. The rest of the
list follows in one compact table with the wording it was given on the day it
entered, so the reader only has to look at the top.

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


B = load("board.json", {"entries": [], "added_today": [], "dropped": []})
L = load("listings.json", {"stats": {}, "listings": []})
C = load("changes.json", {"new": [], "gone": [], "price_changes": []})
S = L.get("stats", {})

date = B.get("date") or S.get("date") or datetime.date.today().isoformat()
site = CFG["site_url"]
doc = CFG["doc_url"]
entries = B.get("entries", [])
added = set(B.get("added_today", []))
fresh = [e for e in entries if e["id"] in added]
subject = (f"Gård-radar {date}: {len(fresh)} new on the list, "
           f"{S.get('matched', '?')} matching, {S.get('price_cuts', 0)} price cuts")


def kr(n):
    return "–" if n is None else f"{int(n):,}".replace(",", " ") + " kr"


def e(s):
    return html.escape(str(s if s is not None else ""))


def facts(x):
    bits = [e(x.get("kommun")), e(x.get("region") or "")]
    if x.get("land_ha") is not None:
        bits.append(f"{x['land_ha']} ha")
    if x.get("living_m2"):
        bits.append(f"{x['living_m2']} m²")
    if x.get("build_year"):
        bits.append(f"byggår {x['build_year']}")
    if x.get("drive_h") is not None:
        bits.append(f"{x['drive_h']} h")
    return " · ".join(b for b in bits if b)


criteria_surv = [
    "Own water: drilled well plus lake or stream on the land",
    "Land: 3 to 30 ha, forest for firewood, some arable or pasture",
    "Low-maintenance house: brick or rendered facade, metal or concrete-tile roof, replaced windows, built 1965 or later",
    "Wood heating installed, secluded access, under 2.5 h from Göteborg",
]
criteria_fin = [
    "Asking price per hectare below the median of all matching listings",
    "Forest and arable carry the value, not the building",
    "Condition: no capital expense surprise in the next ten years",
    "A county with a positive five-year trend and a liquid local market",
]

css = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;color:#1f2a1f;line-height:1.45;margin:0;padding:0;background:#f6f4ee}
.wrap{max-width:940px;margin:0 auto;padding:18px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:22px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}
.sub{color:#666;margin-bottom:12px}
table.t{border-collapse:collapse;width:100%;background:#fff;table-layout:fixed}
table.t th{background:#2f6b3a;color:#fff;text-align:left;padding:8px;font-size:12px;vertical-align:top}
table.t td{border-bottom:1px solid #e3e0d6;padding:8px;vertical-align:top;font-size:13px}
table.t tr:nth-child(even) td{background:#fafaf7}
.rank{font-size:18px;font-weight:700;color:#2f6b3a;text-align:center}
.num{text-align:right;white-space:nowrap}
.new{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;background:#2f5fa8;color:#fff;margin-left:6px}
.rec{font-weight:600}
.small{font-size:12px;color:#666}
ul{margin:4px 0 0 18px;padding:0}li{margin:2px 0}
a{color:#2f6b3a}
.sv{color:#2f6b3a;font-weight:700}.iv{color:#2f5fa8;font-weight:700}
"""

new_rows = []
for x in fresh:
    pos = entries.index(x) + 1
    new_rows.append(f"""
<tr>
 <td class="rank">{pos}</td>
 <td><a href="{e(x.get('url'))}"><b>{e(x.get('title'))}</b></a><span class="new">NEW</span>
     <br><span class="small">{facts(x)} · overall <b>{x.get('score')}</b>,
     survival <span class="sv">{x.get('survival_score')}</span>,
     invest <span class="iv">{x.get('invest_score')}</span></span>
     {('<br><span class="small"><b>Maintenance:</b> ' + e(x.get('maintenance')) + '</span>') if x.get('maintenance') else ''}</td>
 <td>{e(x.get('prepping_why'))}</td>
 <td>{e(x.get('invest_why'))}</td>
 <td>{e(x.get('rank_why'))}</td>
 <td class="rec">{e(x.get('recommendation'))}</td>
</tr>""")

new_block = (f"""<table class="t">
<tr><th style="width:3%">#</th><th style="width:21%">Property</th><th style="width:24%">Why it works for survival</th>
<th style="width:22%">Why it works as an investment</th><th style="width:15%">Why this rank</th><th style="width:15%">Recommendation</th></tr>
{''.join(new_rows)}</table>"""
             if new_rows else
             "<p>Nothing new entered the list today. Everything below is unchanged from yesterday.</p>")

rows = []
for i, x in enumerate(entries, 1):
    is_new = x["id"] in added
    rows.append(f"""<tr>
 <td class="rank">{i}</td>
 <td><a href="{e(x.get('url'))}">{e(x.get('title'))}</a>{'<span class="new">NEW</span>' if is_new else ''}
     <br><span class="small">{facts(x)}</span></td>
 <td class="num">{kr(x.get('price'))}</td>
 <td class="num"><b>{x.get('score')}</b></td>
 <td class="num sv">{x.get('survival_score')}</td>
 <td class="num iv">{x.get('invest_score')}</td>
 <td>{e(x.get('recommendation'))}</td>
</tr>""")

region_rows = "".join(
    f"<tr><td>{e(k)}</td><td class='num'>{v['count']}</td><td class='num'>{v.get('new', 0)}</td>"
    f"<td class='num'>{kr(v.get('median_price'))}</td></tr>"
    for k, v in sorted((S.get("by_region") or {}).items(), key=lambda kv: -kv[1]["count"]))

changed = []
for x in (C.get("price_changes") or [])[:10]:
    arrow = "cut" if x["new"] < x["old"] else "up"
    changed.append(f"<li><b>Price {arrow}:</b> <a href=\"{e(x['url'])}\">{e(x['title'])}</a>, "
                   f"{kr(x['old'])} to {kr(x['new'])}</li>")
for x in (B.get("dropped") or [])[:10]:
    changed.append(f"<li><b>Left the list:</b> {e(x.get('title'))}, {e(x.get('kommun'))} ({e(x.get('why'))})</li>")

html_out = f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="wrap">
<h1>Gård-radar {e(date)}</h1>
<div class="sub">{len(fresh)} new on the list · {len(entries)} on the standing list · {S.get('matched', '?')} matching in total ·
{S.get('price_cuts', 0)} price cuts · median asking {kr(S.get('median_price'))} · median {kr(S.get('median_price_per_ha'))} per ha</div>

<h2>In one paragraph</h2>
<p>{e(B.get('market_summary') or 'No summary written today.')}</p>

<h2>New since the last run</h2>
{new_block}

<h2>The standing list, top {len(entries)}</h2>
<table class="t">
<tr><th style="width:4%">#</th><th style="width:38%">Property</th><th style="width:13%" class="num">Price</th>
<th style="width:8%" class="num">Overall</th><th style="width:8%" class="num">Surv</th><th style="width:8%" class="num">Inv</th>
<th style="width:21%">Recommendation</th></tr>
{''.join(rows) if rows else '<tr><td colspan="7">The list is empty.</td></tr>'}
</table>
<p class="small">Entries keep the wording they were given on the day they entered the list, so only the NEW rows change from day to day.</p>

<h2>What the list is judged on</h2>
<table width="100%"><tr>
<td style="vertical-align:top;width:50%"><b>Survival</b><ul>{''.join(f'<li>{e(x)}</li>' for x in criteria_surv)}</ul></td>
<td style="vertical-align:top;width:50%"><b>Financial</b><ul>{''.join(f'<li>{e(x)}</li>' for x in criteria_fin)}</ul></td>
</tr></table>
<p class="small">Full criteria and weights: <a href="{e(doc)}">plan document</a>, sections 6 and 8.</p>

<h2>Market by region</h2>
<table class="t"><tr><th>Region</th><th class="num">Listings</th><th class="num">New</th><th class="num">Median asking</th></tr>{region_rows}</table>

<h2>Changes</h2>
{('<ul>' + ''.join(changed) + '</ul>') if changed else '<p>No price changes and nothing left the list.</p>'}

<p><a href="{e(site)}"><b>Open the radar site</b></a> · <a href="{e(doc)}">Plan document</a></p>
<p class="small">Sources: Hemnet and Booli, scanned {e(L.get('generated', ''))}. Scores are deterministic; the reasons are Claude's judgement from the day the listing entered the list.</p>
</div></body></html>"""

lines = [f"GÅRD-RADAR {date}",
         f"{len(fresh)} new on the list, {len(entries)} on the standing list, "
         f"{S.get('matched','?')} matching in total", "",
         "IN ONE PARAGRAPH", B.get("market_summary") or "No summary written today.", "",
         "NEW SINCE THE LAST RUN"]
if fresh:
    for x in fresh:
        pos = entries.index(x) + 1
        lines += [f"{pos}. {x.get('title')}, {facts(x)}, {kr(x.get('price'))}",
                  f"   Scores: overall {x.get('score')}, survival {x.get('survival_score')}, invest {x.get('invest_score')}",
                  f"   Survival: {x.get('prepping_why','')}",
                  f"   Investment: {x.get('invest_why','')}",
                  f"   Why this rank: {x.get('rank_why','')}",
                  f"   Maintenance: {x.get('maintenance','')}",
                  f"   Recommendation: {x.get('recommendation','')}",
                  f"   {x.get('url','')}", ""]
else:
    lines += ["Nothing new entered the list today. Everything below is unchanged.", ""]
lines += [f"THE STANDING LIST, TOP {len(entries)}"]
for i, x in enumerate(entries, 1):
    tag = " [NEW]" if x["id"] in added else ""
    lines.append(f"{i}. {x.get('title')}{tag}, {x.get('kommun')}, {kr(x.get('price'))}, "
                 f"O{x.get('score')}/S{x.get('survival_score')}/I{x.get('invest_score')} - {x.get('recommendation','')}")
lines += ["", f"Site: {site}", f"Plan doc: {doc}"]
text_out = "\n".join(lines)

(DATA / "email.html").write_text(html_out, encoding="utf-8")
(DATA / "email.txt").write_text(text_out, encoding="utf-8")
(DATA / "email_subject.txt").write_text(subject, encoding="utf-8")
print(subject)
print(f"html {len(html_out)} chars, text {len(text_out)} chars, {len(fresh)} new of {len(entries)} on the list")
