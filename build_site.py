#!/usr/bin/env python3
"""Render docs/index.html from data/*.json. Pure stdlib, no templates.

Layout (Luki, 2026-09-20): top three as cards with image, link and the two
motivations (survival, investment), then one sortable table of every matching
listing in rank order. Market and change details are folded into a collapsed
block at the bottom.
"""
import glob
import json
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
:root{--bg:#f6f4ee;--card:#fff;--ink:#1f2a1f;--muted:#6b7266;--accent:#2f6b3a;--accent2:#b5541c;--line:#e3e0d6;--blue:#2f5fa8}
@media (prefers-color-scheme:dark){:root{--bg:#141712;--card:#1d221b;--ink:#e9ede4;--muted:#9aa394;--line:#2c3329;--accent:#7fc08a;--accent2:#e58a4d;--blue:#7fa6e8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:26px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{color:var(--muted);margin-bottom:10px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.chip{font-size:12px;padding:3px 9px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--muted)}
.chip b{color:var(--ink)}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--accent);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:4/3;object-fit:cover;background:#ccc}
.card .b{padding:12px 14px 14px;display:flex;flex-direction:column;gap:7px;flex:1}
.t{font-weight:700;font-size:17px}.m{color:var(--muted);font-size:13px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
.price{font-weight:700;font-size:18px}.score{font-weight:700;color:var(--accent);font-size:22px}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;background:var(--accent);color:#fff;white-space:nowrap}
.tag.cut{background:var(--accent2)}.tag.new{background:var(--blue)}.tag.pick{background:var(--accent)}
.why{font-size:14px}.why b{color:var(--accent)}
.rec{font-size:14px;font-weight:600;padding:8px 10px;border-radius:8px;background:var(--bg);border:1px solid var(--line)}
a{color:inherit}
.ctrl{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 12px;align-items:center}
select,input{padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font-size:14px}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:900px}
th{position:sticky;top:0;background:var(--card);color:var(--muted);font-weight:600;font-size:12px;text-align:left;padding:10px 8px;border-bottom:2px solid var(--line);cursor:pointer;user-select:none;white-space:nowrap}
th.on{color:var(--accent)}th.num,td.num{text-align:right}td.num{white-space:nowrap}
th[data-k]:hover{color:var(--ink);background:var(--bg)}
th[data-k] .sa{display:inline-block;margin-left:5px;font-size:10px;opacity:.5;transform:translateY(-1px)}
th[data-k].on .sa{opacity:1}
th[data-k]::after{content:'';display:block}
td{padding:8px;border-bottom:1px solid var(--line);vertical-align:middle}
tr:hover td{background:rgba(47,107,58,.06)}
td.rank{font-weight:700;color:var(--accent);font-size:16px;text-align:center}
td img{width:84px;height:60px;object-fit:cover;border-radius:6px;background:#ccc;display:block}
.obj a{font-weight:600}.obj .m{display:block}
.small{font-size:12px;color:var(--muted)}
details{margin-top:24px}summary{cursor:pointer;font-weight:600;color:var(--muted)}
.note{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.spark{display:flex;align-items:flex-end;gap:2px;height:40px;margin-top:6px}.spark i{display:block;width:8px;background:var(--accent);border-radius:2px 2px 0 0;opacity:.8}
</style>
</head>
<body><div class="wrap">
<h1>Gård-radar</h1>
<div class="sub" id="sub"></div>
<div class="chips" id="chips"></div>

<h2>Top three</h2>
<div id="recs"></div>

<h2>All matching listings, ranked</h2>
<div class="ctrl">
  <select id="fRegion"><option value="">All regions</option></select>
  <input id="fText" placeholder="Filter: kommun, title, broker">
  <label class="small"><input type="checkbox" id="fNew"> only new</label>
  <span class="small" id="count"></span>
  <span class="small" style="opacity:.75">Click any column heading to sort</span>
</div>
<div class="tw"><table id="tbl"><thead><tr>
  <th data-k="rank" class="num on">#</th>
  <th></th>
  <th data-k="title">Property</th>
  <th data-k="price" class="num">Price</th>
  <th data-k="land_ha" class="num">Land</th>
  <th data-k="price_per_ha" class="num">kr/ha</th>
  <th data-k="living_m2" class="num">m²</th>
  <th data-k="build_year" class="num">Built</th>
  <th data-k="drive_h" class="num">Drive</th>
  <th data-k="score" class="num">Score</th>
  <th data-k="days_tracked" class="num">Days</th>
  <th>Status</th>
</tr></thead><tbody id="rows"></tbody></table></div>

<details><summary>Market, regions and changes since the last run</summary><div id="market" style="margin-top:10px"></div></details>

<p class="small" style="margin-top:30px">Sources: Hemnet and Booli (Gård/Skog plus Villa/Hus with 3 ha or more). Score is a deterministic pre-score from listing text and facts; the top three and their reasons are Claude's daily judgement. Criteria live in the shared plan document.</p>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const kr = n => n==null ? '–' : n.toLocaleString('sv-SE') + ' kr';
const esc = s => (s??'').toString().replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const S = D.stats||{}, C = D.changes||{}, R = D.recs||{};
const newIds = new Set((C.new||[]).map(x=>x.id));
const cutIds = new Map((C.price_changes||[]).map(x=>[x.id,x]));
const TOP = (R.top || R.top3 || []);
const pickRank = new Map();
const byId = {}; D.listings.forEach(l=>{ byId[l.id]=l; (l.alt_ids||[]).forEach(a=>byId[a]=l); if (l.alt_url) byId['url:'+l.alt_url]=l; });
const findL = r => byId[r.id] || byId['url:'+r.url] || D.listings.find(l=>l.url===r.url || l.alt_url===r.url) || null;

TOP.forEach((r,i)=>{ const l = findL(r); if (l) pickRank.set(l.id, i+1); });
// rank = position by score (ties by price)
const L = [...D.listings].sort((a,b)=> (b.score-a.score) || (a.price-b.price)).map((l,i)=>({...l, rank:i+1}));

document.getElementById('sub').textContent = `Updated ${D.generated||'?'} · ${kr(D.config.price_min)} to ${kr(D.config.price_max)} · at least ${D.config.land_min_ha} ha · ${Object.keys(D.config.kommuner).length} kommuner within reach of ${D.config.base.name}`;
document.getElementById('chips').innerHTML = [
  ['matching', S.matched], ['new today', S.new], ['gone', S.gone], ['price cuts', S.price_cuts],
  ['median asking', kr(S.median_price)], ['median per ha', kr(S.median_price_per_ha)]
].map(([l,v])=>`<span class="chip"><b>${v??'–'}</b> ${l}</span>`).join('') + (R.date?`<span class="chip">picks dated <b>${esc(R.date)}</b></span>`:'');

// top three cards
let rh='';
if (TOP.length){
  rh = `<div class="grid">` + TOP.slice(0,3).map((r,i)=>{ const L0 = findL(r); const l = L0||{}; const gone = !L0;
    return `<div class="card">${l.image?`<img src="${esc(l.image)}" alt="">`:''}<div class="b">
    <div class="row"><span class="tag pick">#${i+1}</span><span class="score">${r.score??l.score??''}</span></div>
    <div class="t"><a href="${esc(r.url||l.url)}" target="_blank" rel="noopener">${esc(r.title||l.title)}</a>${gone?' <span class="tag cut">no longer listed</span>':''}</div>
    <div class="m">${esc(r.kommun||l.kommun)} · ${esc(r.region||l.region||'')} · ${(r.land_ha||l.land_ha)?(r.land_ha||l.land_ha)+' ha':''}${l.living_m2?' · '+l.living_m2+' m²':''}${l.build_year?' · built '+l.build_year:''}${l.drive_h?' · '+l.drive_h+' h':''}</div>
    <div class="price">${kr(r.price||l.price)}</div>
    <div class="why"><b>Survival:</b> ${esc(r.prepping_why||r.why||'')}</div>
    <div class="why"><b>Investment:</b> ${esc(r.invest_why||'')}</div>
    ${r.maintenance?`<div class="m"><b>Maintenance:</b> ${esc(r.maintenance)}</div>`:''}
    ${r.recommendation?`<div class="rec">${esc(r.recommendation)}</div>`:''}
    </div></div>`}).join('') + `</div>`;
  if (TOP.length>3) rh += `<p class="small" style="margin-top:8px"><b>Also judged worth a look:</b> ` + TOP.slice(3).map((r,i)=>`#${i+4} <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a> (${esc(r.kommun)}, ${kr(r.price)})`).join(' · ') + `</p>`;
  if (R.dropped && R.dropped.length) rh += `<p class="small"><b>Left the list:</b> ` + R.dropped.map(d=>`${esc(d.title)} (${esc(d.why)})`).join('; ') + `</p>`;
} else rh = `<div class="note">No judgement yet. The daily step writes the top three after the scan.</div>`;
document.getElementById('recs').innerHTML = rh;

// table
const regions = [...new Set(L.map(l=>l.region))].sort();
const fR = document.getElementById('fRegion'); regions.forEach(r=>{const o=document.createElement('option');o.value=r;o.textContent=r;fR.appendChild(o)});
let sortKey='rank', sortDir=1;
function status(l){
  const out=[];
  if (pickRank.has(l.id)) out.push(`<span class="tag pick">pick #${pickRank.get(l.id)}</span>`);
  if (newIds.has(l.id)) out.push(`<span class="tag new">new</span>`);
  const c=cutIds.get(l.id); if (c) out.push(`<span class="tag ${c.new<c.old?'cut':''}">${c.new<c.old?'price cut':'price up'}</span>`);
  if (l.upcoming) out.push(`<span class="chip">upcoming</span>`);
  return out.join(' ');
}
function render(){
  const r=fR.value, q=document.getElementById('fText').value.toLowerCase(), onlyNew=document.getElementById('fNew').checked;
  let rows = L.filter(l => (!r || l.region===r) && (!onlyNew || newIds.has(l.id)) && (!q || (l.title+' '+l.kommun+' '+(l.location||'')+' '+(l.broker||'')).toLowerCase().includes(q)));
  rows.sort((a,b)=>{ let x=a[sortKey], y=b[sortKey]; if (typeof x==='string') return sortDir*x.localeCompare(y||'', 'sv'); x=(x==null?Infinity*sortDir:x); y=(y==null?Infinity*sortDir:y); return sortDir*(x-y); });
  document.getElementById('count').textContent = `${rows.length} of ${L.length}`;
  document.getElementById('rows').innerHTML = rows.map(l=>`<tr>
    <td class="rank">${l.rank}</td>
    <td>${l.image?`<a href="${esc(l.url)}" target="_blank" rel="noopener"><img loading="lazy" src="${esc(l.image)}" alt=""></a>`:''}</td>
    <td class="obj"><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a><span class="m">${esc(l.kommun)} · ${esc(l.region)} · ${esc(l.type||'')}${l.alt_url?` · <a href="${esc(l.alt_url)}" target="_blank" rel="noopener">Booli</a>`:''}</span></td>
    <td class="num">${kr(l.price)}</td>
    <td class="num">${l.land_ha!=null?l.land_ha+' ha':'?'}</td>
    <td class="num">${l.price_per_ha?l.price_per_ha.toLocaleString('sv-SE'):'–'}</td>
    <td class="num">${l.living_m2??'–'}</td>
    <td class="num">${l.build_year??'–'}</td>
    <td class="num">${l.drive_h!=null?l.drive_h+' h':'–'}</td>
    <td class="num"><b>${l.score}</b></td>
    <td class="num">${l.days_tracked??'–'}</td>
    <td>${status(l)}</td>
  </tr>`).join('') || `<tr><td colspan="12" class="small">Nothing matches these filters.</td></tr>`;
  document.querySelectorAll('th[data-k]').forEach(th=>{
    if (!th.querySelector('.sa')) th.insertAdjacentHTML('beforeend', '<span class="sa"></span>');
    const on = th.dataset.k===sortKey;
    th.classList.toggle('on', on);
    th.title = on ? 'Sorted by this column, click to reverse' : 'Click to sort by this column';
    th.querySelector('.sa').textContent = on ? (sortDir===1 ? '\u25B2' : '\u25BC') : '\u21C5';
  });
}
document.querySelectorAll('th[data-k]').forEach(th=>th.addEventListener('click',()=>{ const k=th.dataset.k; if (sortKey===k) sortDir=-sortDir; else { sortKey=k; sortDir = (k==='rank'||k==='price'||k==='price_per_ha'||k==='drive_h'||k==='title') ? 1 : -1; } render(); }));
['fRegion','fText','fNew'].forEach(id=>document.getElementById(id).addEventListener('input',render));
render();

// collapsed market block
let mh = R.market_summary ? `<div class="note">${esc(R.market_summary)}</div>` : '';
const reg = S.by_region||{};
mh += `<table style="min-width:0;margin-top:12px"><tr><th>Region</th><th class="num">Listings</th><th class="num">New</th><th class="num">Median asking</th></tr>` +
  Object.entries(reg).sort((a,b)=>b[1].count-a[1].count).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="num">${v.count}</td><td class="num">${v.new}</td><td class="num">${kr(v.median_price)}</td></tr>`).join('') + `</table>`;
const fmtTot = v => v==null ? '–' : (typeof v==='object' ? Object.entries(v).map(([k,n])=>`${n??'–'} ${k}`).join(', ') : v);
if (S.national_in_band) mh += `<p class="small">Nationally in the price band: Hemnet ${fmtTot(S.national_in_band.hemnet)}; Booli ${fmtTot(S.national_in_band.booli)}.</p>`;
let ch='';
(C.new||[]).forEach(x=> ch += `<li><span class="tag new">new</span> <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>, ${esc(x.kommun)}, ${kr(x.price)}, score ${x.score}</li>`);
(C.price_changes||[]).forEach(x=> ch += `<li><span class="tag ${x.new<x.old?'cut':''}">${x.new<x.old?'price cut':'price up'}</span> <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>, ${kr(x.old)} to ${kr(x.new)}</li>`);
(C.gone||[]).forEach(x=> ch += `<li><span class="chip">gone</span> ${esc(x.title)}, ${esc(x.kommun)}, ${kr(x.price)}</li>`);
mh += ch ? `<ul style="margin-top:10px">${ch}</ul>` : `<p class="small" style="margin-top:10px">No changes since the last run.</p>`;
if (D.history && D.history.length>1){
  const max = Math.max(...D.history.map(h=>h.matched||0),1);
  mh += `<div class="small">Matching listings, last ${D.history.length} runs</div><div class="spark">` + D.history.map(h=>`<i title="${h.date}: ${h.matched}" style="height:${Math.max(3,Math.round(40*h.matched/max))}px"></i>`).join('') + `</div>`;
}
document.getElementById('market').innerHTML = mh;
</script>
</body></html>
"""
(DOCS / "index.html").write_text(page.replace("__DATA__", json_blob), encoding="utf-8")
print(f"site built: {len(payload['listings'])} listings, recs={'yes' if recs else 'no'} -> {DOCS/'index.html'}")
