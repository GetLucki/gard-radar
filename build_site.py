#!/usr/bin/env python3
"""Render docs/index.html from data/*.json. Pure stdlib, no templates."""
import datetime
import glob
import html
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
(DOCS / "data").mkdir(parents=True, exist_ok=True)
CFG = json.load(open(ROOT / "config.json", encoding="utf-8"))


def load(name, default):
    try:
        return json.load(open(DATA / name, encoding="utf-8"))
    except Exception:
        return default


listings = load("listings.json", {"stats": {}, "listings": []})
changes = load("changes.json", {"new": [], "gone": [], "price_changes": []})
recs = load("recommendations.json", {})
history = []
for f in sorted(glob.glob(str(DATA / "history" / "*.json")))[-30:]:
    try:
        h = json.load(open(f, encoding="utf-8"))
        history.append({"date": h["date"], "matched": h["stats"]["matched"],
                        "median_price": h["stats"].get("median_price"), "new": h["stats"].get("new", 0)})
    except Exception:
        pass

# public copies (without the big details cache)
for name in ("listings.json", "changes.json", "recommendations.json"):
    if (DATA / name).exists():
        (DOCS / "data" / name).write_bytes((DATA / name).read_bytes())
(DOCS / ".nojekyll").write_text("")

payload = {
    "generated": listings.get("generated"),
    "config": CFG,
    "stats": listings.get("stats", {}),
    "listings": listings.get("listings", []),
    "changes": changes,
    "recs": recs,
    "history": history,
}
json_blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

page = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gård-radar</title>
<style>
:root{--bg:#f6f4ee;--card:#fff;--ink:#1f2a1f;--muted:#6b7266;--accent:#2f6b3a;--accent2:#b5541c;--line:#e3e0d6;--good:#2f6b3a;--warn:#b5541c}
@media (prefers-color-scheme:dark){:root{--bg:#141712;--card:#1d221b;--ink:#e9ede4;--muted:#9aa394;--line:#2c3329;--accent:#7fc08a;--accent2:#e58a4d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:28px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{color:var(--muted);margin-bottom:18px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;background:#ccc}
.card .b{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
.t{font-weight:600;font-size:16px}.m{color:var(--muted);font-size:13px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
.price{font-weight:700;font-size:17px}.score{font-weight:700;color:var(--accent);font-size:20px}
.chips{display:flex;flex-wrap:wrap;gap:4px}.chip{font-size:11px;padding:2px 7px;border-radius:999px;background:var(--bg);border:1px solid var(--line);color:var(--muted)}
.chip.on{color:var(--accent);border-color:var(--accent)}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;background:var(--accent);color:#fff}
.tag.cut{background:var(--accent2)}.tag.new{background:#2f5fa8}
a{color:inherit}.links a{font-size:13px;color:var(--accent);margin-right:10px}
.stats{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stat .v{font-size:26px;font-weight:700}.stat .l{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600;font-size:12px}
.top{border-left:5px solid var(--accent)}.why{font-size:14px}
.ctrl{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 14px}select,input{padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
.note{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;white-space:pre-wrap}
.small{font-size:12px;color:var(--muted)}
.spark{display:flex;align-items:flex-end;gap:2px;height:40px}.spark i{display:block;width:8px;background:var(--accent);border-radius:2px 2px 0 0;opacity:.8}
</style>
</head>
<body><div class="wrap">
<h1>Gård-radar</h1>
<div class="sub" id="sub"></div>
<div class="stats" id="stats"></div>

<h2>Today's top three</h2>
<div id="recs"></div>

<h2>Market situation</h2>
<div id="market"></div>

<h2>Changes since last run</h2>
<div id="changes"></div>

<h2>All matching listings</h2>
<div class="ctrl">
  <select id="fRegion"><option value="">All regions</option></select>
  <select id="fSort"><option value="score">Sort: score</option><option value="price">Sort: price</option><option value="ha">Sort: land</option><option value="new">Sort: newest</option><option value="drive">Sort: drive time</option></select>
  <input id="fText" placeholder="Filter text (kommun, title)">
</div>
<div class="grid" id="list"></div>
<p class="small" style="margin-top:30px">Sources: Hemnet (Gård/Skog) and Booli (Gård). Scores are a deterministic pre-score from listing text and facts; the top three are Claude's daily judgement. Criteria live in the shared plan document.</p>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const kr = n => n==null ? '–' : n.toLocaleString('sv-SE') + ' kr';
const esc = s => (s??'').toString().replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const newIds = new Set((D.changes.new||[]).map(x=>x.id));
const cutIds = new Map((D.changes.price_changes||[]).map(x=>[x.id,x]));
const S = D.stats||{};
document.getElementById('sub').textContent = `Updated ${D.generated||'?'} · ${kr(D.config.price_min)} to ${kr(D.config.price_max)} · at least ${D.config.land_min_ha} ha · ${Object.keys(D.config.kommuner).length} kommuner within reach of ${D.config.base.name}`;
document.getElementById('stats').innerHTML = [
  ['Matching listings', S.matched], ['New today', S.new], ['Gone', S.gone], ['Price cuts', S.price_cuts],
  ['Median asking', kr(S.median_price)], ['Median kr/ha', kr(S.median_price_per_ha)]
].map(([l,v])=>`<div class="stat"><div class="v">${v??'–'}</div><div class="l">${l}</div></div>`).join('');

// recommendations
const R = D.recs||{}; const byId = Object.fromEntries(D.listings.map(l=>[l.id,l]));
let rh='';
if (R.top3 && R.top3.length){
  rh += `<div class="grid">` + R.top3.map((r,i)=>{ const l = byId[r.id]||{}; return `<div class="card top">${l.image?`<img src="${esc(l.image)}" alt="">`:''}<div class="b">
    <div class="row"><span class="tag">#${i+1}</span><span class="score">${r.score??l.score??''}</span></div>
    <div class="t"><a href="${esc(r.url||l.url)}" target="_blank" rel="noopener">${esc(r.title||l.title)}</a></div>
    <div class="m">${esc(r.kommun||l.kommun)} · ${esc(l.region||'')} · ${l.land_ha?l.land_ha+' ha':''} ${l.living_m2?'· '+l.living_m2+' m²':''} ${l.drive_h?'· '+l.drive_h+' h':''}</div>
    <div class="price">${kr(r.price||l.price)}</div>
    <div class="why">${esc(r.why)}</div></div></div>`}).join('') + `</div>`;
  if (R.dropped && R.dropped.length) rh += `<p class="small" style="margin-top:10px"><b>Dropped from the top three:</b> ` + R.dropped.map(d=>`${esc(d.title)} (${esc(d.why)})`).join('; ') + `</p>`;
  rh += `<p class="small">Recommendations dated ${esc(R.date||'')}.</p>`;
} else rh = `<div class="note">No recommendations yet. The Claude step writes them after the first full run.</div>`;
document.getElementById('recs').innerHTML = rh;

// market
let mh = R.market_summary ? `<div class="note">${esc(R.market_summary)}</div>` : '';
const reg = S.by_region||{};
mh += `<table style="margin-top:12px"><tr><th>Region</th><th>Listings</th><th>New</th><th>Median asking</th></tr>` +
  Object.entries(reg).sort((a,b)=>b[1].count-a[1].count).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v.count}</td><td>${v.new}</td><td>${kr(v.median_price)}</td></tr>`).join('') + `</table>`;
if (S.national_in_band) mh += `<p class="small">Nationally in the price band today: Hemnet ${S.national_in_band.hemnet??'–'} gårdar, Booli ${S.national_in_band.booli??'–'}.</p>`;
if (D.history && D.history.length>1){
  const max = Math.max(...D.history.map(h=>h.matched||0),1);
  mh += `<div class="small" style="margin-top:8px">Matching listings, last ${D.history.length} runs</div><div class="spark">` + D.history.map(h=>`<i title="${h.date}: ${h.matched}" style="height:${Math.max(3,Math.round(40*h.matched/max))}px"></i>`).join('') + `</div>`;
}
document.getElementById('market').innerHTML = mh;

// changes
const C = D.changes||{}; let ch='';
if (C.first_run) ch += `<div class="note">First run: everything counts as new. Changes will be meaningful from tomorrow.</div>`;
else {
  ch += `<table><tr><th>Type</th><th>Listing</th><th>Kommun</th><th>Price</th></tr>`;
  (C.new||[]).forEach(x=> ch += `<tr><td><span class="tag new">new</span></td><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a></td><td>${esc(x.kommun)}</td><td>${kr(x.price)} · score ${x.score}</td></tr>`);
  (C.price_changes||[]).forEach(x=> ch += `<tr><td><span class="tag ${x.new<x.old?'cut':''}">${x.new<x.old?'price cut':'price up'}</span></td><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a></td><td>${esc(x.kommun)}</td><td>${kr(x.old)} → ${kr(x.new)}</td></tr>`);
  (C.gone||[]).forEach(x=> ch += `<tr><td><span class="chip">gone</span></td><td>${esc(x.title)}</td><td>${esc(x.kommun)}</td><td>${kr(x.price)} · tracked ${x.days_tracked??'?'} d</td></tr>`);
  ch += `</table>`;
  if (!(C.new||[]).length && !(C.price_changes||[]).length && !(C.gone||[]).length) ch = `<div class="note">No changes since the last run.</div>`;
}
document.getElementById('changes').innerHTML = ch;

// list
const regions = [...new Set(D.listings.map(l=>l.region))].sort();
const fR = document.getElementById('fRegion'); regions.forEach(r=>{const o=document.createElement('option');o.value=r;o.textContent=r;fR.appendChild(o)});
const PARTS = {water:'water',land:'land',buildings:'buildings',heating:'heat',seclusion:'seclusion',drive:'drive',price:'price',income:'income'};
function render(){
  const r = fR.value, s = document.getElementById('fSort').value, q = document.getElementById('fText').value.toLowerCase();
  let L = D.listings.filter(l => (!r || l.region===r) && (!q || (l.title+' '+l.kommun+' '+(l.location||'')).toLowerCase().includes(q)));
  const key = {score:l=>-l.score, price:l=>l.price, ha:l=>-(l.land_ha||0), new:l=>-(new Date(l.first_seen)), drive:l=>l.drive_h??99}[s];
  L.sort((a,b)=>key(a)-key(b));
  document.getElementById('list').innerHTML = L.map(l=>{
    const cut = cutIds.get(l.id); const parts = l.score_parts||{};
    return `<div class="card">${l.image?`<img loading="lazy" src="${esc(l.image)}" alt="">`:''}<div class="b">
      <div class="row"><div>${newIds.has(l.id)?'<span class="tag new">new</span> ':''}${cut?`<span class="tag ${cut.new<cut.old?'cut':''}">${cut.new<cut.old?'price cut':'price up'}</span> `:''}${l.upcoming?'<span class="chip">upcoming</span>':''}</div><span class="score">${l.score}</span></div>
      <div class="t"><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a></div>
      <div class="m">${esc(l.kommun)} · ${esc(l.region)} · ${esc(l.type||'')}</div>
      <div class="row"><span class="price">${kr(l.price)}</span><span class="m">${l.land_ha?l.land_ha+' ha':'land ?'}${l.price_per_ha?' · '+kr(l.price_per_ha)+'/ha':''}</span></div>
      <div class="m">${l.living_m2?l.living_m2+' m² · ':''}${esc(l.rooms||'')}${l.drive_h?' · '+l.drive_h+' h from '+esc(D.config.base.name):''} · tracked ${l.days_tracked} d</div>
      <div class="chips">${Object.entries(PARTS).map(([k,lab])=>`<span class="chip ${parts[k]>0?'on':''}">${lab} ${parts[k]??0}</span>`).join('')}</div>
      <div class="chips">${(l.signals||[]).map(x=>`<span class="chip on">${esc(x)}</span>`).join('')}</div>
      <div class="links"><a href="${esc(l.url)}" target="_blank" rel="noopener">${l.source==='hemnet'?'Hemnet':'Booli'}</a>${l.alt_url?`<a href="${esc(l.alt_url)}" target="_blank" rel="noopener">Booli</a>`:''}<span class="small">${esc(l.broker||'')}</span></div>
    </div></div>`}).join('') || '<div class="note">Nothing matches these filters.</div>';
}
['fRegion','fSort','fText'].forEach(id=>document.getElementById(id).addEventListener('input',render)); render();
</script>
</body></html>
"""
(DOCS / "index.html").write_text(page.replace("__DATA__", json_blob), encoding="utf-8")
print(f"site built: {len(payload['listings'])} listings, recs={'yes' if recs else 'no'} -> {DOCS/'index.html'}")
