#!/usr/bin/env python3
"""Gård-radar scanner.

Scrapes Hemnet (Gård/Skog) and Booli (Gård) inside the configured price band,
keeps listings in the kommun whitelist with enough land, fetches the full
description for listings not seen before, pre-scores them deterministically and
writes the data files the site builder and the Claude step read.

Outputs (all under data/):
  listings.json      current matching listings with scores and stats
  changes.json       new / gone / price changes versus the previous run
  seen.json          first-seen date and price history per listing id
  details.json       cached full descriptions (gitignored, large)
  digest_input.json  compact input for the Claude step
  history/DATE.json  compact daily snapshot for trend charts
"""
import datetime
import json
import math
import random
import pathlib
import re
import statistics
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HIST = DATA / "history"
DATA.mkdir(exist_ok=True)
HIST.mkdir(exist_ok=True)
CFG = json.load(open(ROOT / "config.json", encoding="utf-8"))
TODAY = datetime.date.today().isoformat()
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
MAX_PAGES = 40
DETAIL_LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 80


def log(msg):
    print(f"{datetime.datetime.now():%H:%M:%S} {msg}", flush=True)


def load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


# ---------- parsing helpers ----------

def parse_price(s):
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def parse_area_ha(s):
    if not s:
        return None
    t = s.lower().replace(" ", " ")
    m = re.search(r"(\d[\d ]*(?:[,.]\d+)?)\s*(ha|hektar|m²|m2|kvm)", t)
    if not m:
        return None
    num = float(m.group(1).replace(" ", "").replace(",", "."))
    unit = m.group(2)
    return round(num if unit in ("ha", "hektar") else num / 10000, 2)


def parse_m2(s):
    if not s:
        return None
    m = re.search(r"(\d[\d ]*)\s*(?:\+\s*(\d[\d ]*))?\s*m", s.replace(" ", " "))
    if not m:
        return None
    return int(m.group(1).replace(" ", ""))


KOMMUN_INDEX = {}
for _k in CFG["kommuner"]:
    KOMMUN_INDEX[_k.lower()] = _k
    KOMMUN_INDEX[(_k + "s").lower()] = _k  # Hemnet genitive: "Falkenbergs kommun"


def match_kommun(name):
    if not name:
        return None
    return KOMMUN_INDEX.get(name.strip().lower())


def kommun_from_location(text):
    m = re.search(r"([A-Za-zÅÄÖåäöéÉ\- ]+?)\s+kommun", text or "")
    return m.group(1).strip() if m else None


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def drive_hours(kommun, lat, lon):
    if kommun in CFG["kommuner"]:
        return CFG["kommuner"][kommun]["drive_h"]
    if lat and lon:
        b = CFG["base"]
        return round(haversine_km(lat, lon, b["lat"], b["lon"]) * 1.35 / 75, 1)
    return None


def apollo_state(page):
    raw = page.locator("#__NEXT_DATA__").inner_text(timeout=20000)
    nd = json.loads(raw)
    return nd["props"]["pageProps"].get("__APOLLO_STATE__", {})


def goto_state(browser, url, tries=3):
    """Open url in a FRESH browser context and return (ctx, page, apollo_state).

    Both Hemnet and Booli serve the first request of a session normally and
    challenge the second one (Cloudflare "Vänta..."), so every page load gets
    its own context with no cookies. The caller closes ctx.
    """
    last = None
    for attempt in range(1, tries + 1):
        ctx = browser.new_context(user_agent=UA, locale="sv-SE", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(60000)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#__NEXT_DATA__", state="attached", timeout=15000)
            time.sleep(random.uniform(0.8, 1.8))
            return ctx, page, apollo_state(page)
        except Exception as e:
            last = e
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            ctx.close()
            log(f"  retry {attempt}/{tries} for {url[:80]} (title: {title[:40]!r})")
            time.sleep(4 * attempt)
    raise RuntimeError(f"could not load {url}: {last}")


# ---------- Hemnet ----------

HEMNET_SEARCHES = {
    "gard": "https://www.hemnet.se/bostader?item_types%5B%5D=gard&price_min={pmin}&price_max={pmax}&page=",
    # houses filed as Villa but with farm-sized plots (a 1970s brick villa on 5 ha is usually here)
    "villa": "https://www.hemnet.se/bostader?item_types%5B%5D=villa&price_min={pmin}&price_max={pmax}&land_area_min={lmin}&page=",
}
BOOLI_SEARCHES = {
    "gard": "https://www.booli.se/sok/till-salu?objectType=g%C3%A5rd&minListPrice={pmin}&maxListPrice={pmax}&page=",
    "hus": "https://www.booli.se/sok/till-salu?objectType=hus&minListPrice={pmin}&maxListPrice={pmax}&minPlotArea={lmin}&page=",
}


def _fmt(u):
    return u.format(pmin=CFG["price_min"], pmax=CFG["price_max"], lmin=int(CFG["land_min_ha"] * 10000))


def scrape_hemnet(browser, base=None):
    base = _fmt(base or HEMNET_SEARCHES["gard"])
    out, total = [], None
    for n in range(1, MAX_PAGES + 1):
        ctx, page, ap = goto_state(browser, base + str(n), tries=3)
        ctx.close()
        if total is None:
            for k, v in ap.get("ROOT_QUERY", {}).items():
                if k.startswith("searchForSaleListings") and isinstance(v, dict) and "total" in v:
                    total = v["total"]
                    break
        cards = [v for k, v in ap.items() if k.startswith("ListingCard:")]
        if not cards:
            break
        for c in cards:
            loc = c.get("locationDescription") or ""
            coords = c.get("coordinates") or {}
            thumbs = None
            for key, val in c.items():
                if key.startswith("thumbnails(") and val:
                    thumbs = val
                    break
            out.append({
                "id": f"hemnet:{c['id']}",
                "source": "hemnet",
                "title": c.get("streetAddress") or loc,
                "location": loc,
                "kommun_raw": kommun_from_location(loc),
                "price": parse_price(c.get("askingPrice")),
                "land_ha": parse_area_ha(c.get("landArea")),
                "living_m2": parse_m2(c.get("livingAndSupplementalAreas")),
                "rooms": c.get("rooms"),
                "type": (c.get("housingForm") or {}).get("name"),
                "url": f"https://www.hemnet.se/bostad/{c.get('slug')}",
                "lat": coords.get("lat"),
                "lon": coords.get("long"),
                "published": datetime.date.fromtimestamp(float(c["publishedAt"])).isoformat() if c.get("publishedAt") else None,
                "broker": c.get("brokerAgencyName"),
                "teaser": c.get("description") or "",
                "image": thumbs[0] if thumbs else None,
                "upcoming": bool(c.get("upcoming")),
                "labels": [l.get("identifier") for l in c.get("labels") or [] if isinstance(l, dict)],
            })
        log(f"hemnet page {n}: {len(cards)} cards (total {total})")
        if total is not None and n * 50 >= total:
            break
    return out, total


# ---------- Booli ----------

def scrape_booli(browser, base=None):
    base = _fmt(base or BOOLI_SEARCHES["gard"])
    out, total = [], None
    for n in range(1, MAX_PAGES + 1):
        ctx, page, ap = goto_state(browser, base + str(n))
        ctx.close()
        if total is None:
            for k, v in ap.get("ROOT_QUERY", {}).items():
                if k.startswith("searchForSaleV2") and isinstance(v, dict) and v.get("totalCount"):
                    total = v["totalCount"]
                    break
        props = [v for k, v in ap.items() if k.startswith("ListableProperty:")]
        if not props:
            break
        for p in props:
            tr = ((p.get("tracking") or {}).get("properties") or {})
            dps = {d.get("key"): (d.get("value") or {}).get("plainText")
                   for d in ((p.get("displayAttributes") or {}).get("dataPoints") or [])}
            pos = p.get("position") or {}
            img = None
            for key, val in p.items():
                if key.startswith("images(") and val:
                    ref = val[0].get("__ref") if isinstance(val[0], dict) else None
                    img = ref  # resolved below
                    break
            url = p.get("url") or ""
            out.append({
                "id": f"booli:{p.get('listingId')}",
                "source": "booli",
                "title": p.get("title"),
                "location": p.get("subtitle"),
                "kommun_raw": tr.get("municipality"),
                "county": tr.get("county"),
                "price": parse_price(p.get("displayPrice")),
                "land_ha": parse_area_ha(dps.get("rentOrPlotAreaText") or dps.get("plotArea")),
                "living_m2": parse_m2(dps.get("livingArea")),
                "rooms": dps.get("rooms"),
                "type": p.get("objectType"),
                "url": ("https://www.booli.se" + url) if url.startswith("/") else url,
                "lat": pos.get("latitude"),
                "lon": pos.get("longitude"),
                "published": None,
                "days_text": p.get("displayDate"),
                "broker": (p.get("presenter") or {}).get("name"),
                "teaser": "",
                "image_ref": img,
                "upcoming": bool(tr.get("upcoming_sale")),
                "labels": [],
            })
            # resolve image: Booli's Image objects carry only an id, and the
            # CDN url is built from it (verified 2026-09-20; before this, all
            # Booli-only listings showed no photo at all).
            if img and img in ap:
                imgobj = ap[img]
                url_direct = imgobj.get("url") or imgobj.get("src")
                iid = imgobj.get("id") or (img.split(":")[-1] if ":" in img else None)
                out[-1]["image"] = url_direct or (f"https://bcdn.se/images/cache/{iid}_1440x0.jpg" if iid else None)
            out[-1].pop("image_ref", None)
        log(f"booli page {n}: {len(props)} props (total {total})")
        if total is not None and n * 35 >= total:
            break
    return out, total


# ---------- filtering, dedupe ----------

def passes(l):
    k = match_kommun(l.get("kommun_raw"))
    if not k:
        return False
    l["kommun"] = k
    l["region"] = CFG["kommuner"][k]["region"]
    if l.get("price") is None or not (CFG["price_min"] <= l["price"] <= CFG["price_max"]):
        return False
    ha = l.get("land_ha")
    if ha is None:
        return bool(CFG.get("keep_unknown_land", True))
    return ha >= CFG["land_min_ha"]


def _norm_title(t):
    return re.sub(r"[^a-zåäö0-9]", "", (t or "").lower())


def stable_key(l):
    """Source-independent identity: kommun + normalised title + price rounded
    to 10 000 kr. A listing that moves from a Hemnet id to a Booli id (or
    back) keeps its history."""
    return f"{(l.get('kommun') or '').lower()}|{_norm_title(l.get('title'))}|{round((l.get('price') or 0) / 10000)}"


def dedupe(listings):
    """Merge Booli duplicates into Hemnet entries when price and position agree."""
    hemnet = [l for l in listings if l["source"] == "hemnet"]
    booli = [l for l in listings if l["source"] == "booli"]
    merged = list(hemnet)
    kept_booli = []
    for b in booli:
        dup = None
        for h in hemnet + kept_booli:
            if h.get("kommun") != b.get("kommun"):
                continue
            same_price = abs((h["price"] or 0) - (b["price"] or 0)) <= 0.01 * max(h["price"] or 1, 1)
            if not same_price:
                continue
            near = bool(h.get("lat") and b.get("lat")) and haversine_km(h["lat"], h["lon"], b["lat"], b["lon"]) < 0.4
            same_name = _norm_title(h.get("title")) and _norm_title(h.get("title")) == _norm_title(b.get("title"))
            same_land = h.get("land_ha") and b.get("land_ha") and abs(h["land_ha"] - b["land_ha"]) <= 0.05 * max(h["land_ha"], 0.1)
            if near or same_name or (same_land and (h.get("lat") is None or b.get("lat") is None)):
                dup = h
                break
        if dup:
            dup["alt_ids"] = sorted(set(dup.get("alt_ids", []) + [b["id"]]))
            if dup["source"] == "hemnet":
                dup["alt_url"] = b["url"]
                dup["days_text"] = b.get("days_text")
            if not dup.get("land_ha") and b.get("land_ha"):
                dup["land_ha"] = b["land_ha"]
        else:
            merged.append(b)
            kept_booli.append(b)
    return merged


# ---------- detail pages ----------

def fetch_detail(browser, l):
    text = ""
    ap = None
    ctx = page = None
    try:
        ctx, page, ap = goto_state(browser, l["url"], tries=2)
    except Exception:
        return ""
    try:
        if l["source"] == "hemnet" and ap:
            for k, v in ap.items():
                if k.startswith("ActivePropertyListing") and isinstance(v, dict):
                    desc = v.get("description") or ""
                    extra = []
                    for kk, vv in v.items():
                        if kk in ("description", "__typename") or kk.startswith("images") or kk.startswith("thumbnails"):
                            continue
                        if isinstance(vv, (str, int, float)) and str(vv).strip():
                            extra.append(f"{kk}: {vv}")
                        elif isinstance(vv, dict) and vv.get("name"):
                            extra.append(f"{kk}: {vv['name']}")
                        elif isinstance(vv, list) and vv and all(isinstance(x, str) for x in vv):
                            extra.append(f"{kk}: {', '.join(vv[:12])}")
                    text = desc + "\nFAKTA\n" + "\n".join(extra)
                    if v.get("landArea"):
                        l["land_ha"] = parse_area_ha(str(v["landArea"]) + " m²") or l.get("land_ha")
                    break
        if not text:
            text = page.evaluate("""() => {
                const h = [...document.querySelectorAll('h2,h3')].find(x => /beskrivning|om bostaden|om fastigheten/i.test(x.textContent));
                let t = '';
                if (h) { let el = h.nextElementSibling; let n = 0; while (el && n < 12) { t += el.innerText + '\\n'; el = el.nextElementSibling; n++; } }
                document.querySelectorAll('[id*="cookie" i],[class*="cookie" i],[id*="consent" i],[class*="consent" i],[id*="Cybot" i],[class*="onetrust" i],[aria-label*="cookie" i]').forEach(x => x.remove());
                const body = document.body.innerText || '';
                const facts = body.split('\\n').filter(l => /byggår|boarea|biarea|tomtarea|areal|fasad|^tak|taktyp|uppvärmning|vatten|avlopp|energiklass|driftkostnad|grund|fönster|ventilation|byggnadstyp|stomme/i.test(l) && l.length < 160);
                const desc = t.trim().length > 200 ? t : body.slice(0, 6000);
                return desc + '\\nFAKTA\\n' + [...new Set(facts)].slice(0, 40).join('\\n');
            }""")
    except Exception:
        text = text or ""
    finally:
        if ctx:
            ctx.close()
    # Booli often has no photo on the search card but plenty on the listing page
    # (verified 2026-09-20). Take the first one when the card gave us nothing.
    if ap and not l.get("image"):
        for k, v in ap.items():
            if k.startswith("Image") and isinstance(v, dict):
                iid = v.get("id") or k.split(":")[-1]
                direct = v.get("url") or v.get("src")
                if direct or iid:
                    l["image"] = direct or f"https://bcdn.se/images/cache/{iid}_1440x0.jpg"
                    break
    try:
        title = page.title() if page else ""
    except Exception:
        title = ""
    text = (title + "\n" + (text or "")) if title else (text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:8000]


# ---------- scoring ----------

KW = {
    "well": r"egen brunn|borrad brunn|djupborrad|grävd brunn|bergborrad|\bbrunn\b",
    "water": r"sjötomt|egen strand|strandlinje|sjöutsikt|badplats|sjönära|vid sjön|\bsjö\b|bäck|vattendrag|fiskerätt|fiskevatten|\bå\b|älv",
    "forest": r"produktiv skog|skogsmark|\bskog\b|m3sk|m³sk|skogsbruksplan|virkesförråd",
    "arable": r"åker|åkermark|\bbete\b|betesmark|hagmark|inägomark|jordbruksmark|\bäng\b|ängsmark|vall\b",
    "second_dwelling": r"gäststuga|gästhus|flygel|uthyrningsstuga|två bostadshus|ytterligare bostad|extra bostad|attefallshus|\btorp\b|lillstuga|drängstuga",
    "barn": r"ladugård|ekonomibyggnad|\bloge\b|\bstall\b|maskinhall|verkstad|lada\b|magasin",
    "wood_heat": r"vedspis|kakelugn|vedpanna|braskamin|\bkamin\b|vedeldad|öppen spis|järnspis|vedeldning",
    "seclusion": r"enskilt läge|avskilt|ostört|återvändsväg|insynsskyddat|skogsglänta|längst in|egen väg|lugnt läge",
    "income": r"uthyrning|bed and breakfast|b&b|turism|camping|glamping|verksamhet|hästgård|besöksnäring",
    # low-maintenance house signals (Luki 2026-09-17: the house must not need painting or constant care)
    "lowmaint_facade": r"tegelfasad|tegelhus|fasad i tegel|putsad|putsat|stenhus|mexitegel|betongsten|underhållsfri",
    "lowmaint_roof": r"plåttak|betongpannor|betongtegel|nytt tak|omlagt tak|takomläggning|nylagt tak|tak(et)? (är )?(bytt|omlagt|nytt)",
    "lowmaint_windows": r"nya fönster|fönster(na)? (är )?bytta|3-glas|treglas|aluminiumfönster|aluminiumbeklädda|pvc-fönster",
    "lowmaint_renovated": r"totalrenoverad|helrenoverad|genomgående renoverad|nyrenoverad|renoverad 20[12]\d|omfattande renoverad|nybyggd|nyproduktion",
    "highmaint_log": r"timmerhus|timrat|timmerstomme|1[78]\d\d-tal|från 1[78]\d\d|byggd 1[78]\d\d|1800-tal|sekelskifte",
    "highmaint_need": r"renoveringsbehov|renoveringsobjekt|i behov av (renovering|upprustning|underhåll)|upprustningsbehov|handlingens|för den handlingskraftige|eftersatt|ödegård|rivningsobjekt",
    "highmaint_defects": r"eternit|asbest|torpargrund|fuktskad|mögel|sättningar|takläckage|enkelglas|självdrag",
}


def build_year(text):
    m = re.search(r"(?:byggår|constructionyear|byggd|uppförd|byggt)[:\s]*(\d{4})", (text or "").lower())
    if m:
        y = int(m.group(1))
        if 1600 < y < 2030:
            return y
    return None


def _phrase(lang, en, sv):
    return sv if lang == "sv" else en


def score(l, text, median_price_per_ha):
    """Three scores (doc section 8, split 2026-09-20 at Luki's request):

      survival_score  0-100  can the family live here when nothing is delivered
      invest_score    0-100  is the money well placed if the crisis never comes
      score           0-100  overall, the mean of the two, used for ranking

    Each comes with a short plain-language motivation so the table can show why.
    """
    lang = CFG.get("lang", "en")
    t = (text or "") + " " + (l.get("teaser") or "") + " " + (l.get("type") or "")
    t = t.lower()
    hit = {k: bool(re.search(p, t)) for k, p in KW.items()}
    ha = l.get("land_ha") or 0
    d = l.get("drive_h")
    y = build_year(text)
    l["build_year"] = y

    # --- shared building blocks -------------------------------------------
    forest = 2 if (ha >= 5 and hit["forest"]) else (1 if (ha >= 5 or hit["forest"]) else 0)
    # condition, 0..10: the same evidence drives survival robustness and resale
    cond = 4
    cond += 2 if hit["lowmaint_facade"] else 0
    cond += 2 if hit["lowmaint_roof"] else 0
    cond += 1 if hit["lowmaint_windows"] else 0
    cond += 2 if hit["lowmaint_renovated"] else 0
    cond += 2 if (y and y >= 1965) else 0
    if (y and y < 1920) or hit["highmaint_log"]:
        cond -= 4 if not hit["lowmaint_renovated"] else 1
    cond -= 4 if hit["highmaint_need"] else 0
    cond -= 2 if hit["highmaint_defects"] else 0
    cond = max(0, min(10, cond))

    # --- survival ----------------------------------------------------------
    sv = {}
    sv["water"] = (12 if hit["well"] else 0) + (13 if hit["water"] else 0)      # 25
    sv["land"] = (10 if forest == 2 else 5 if forest == 1 else 0) + (10 if hit["arable"] else 0)  # 20
    sv["heating"] = 15 if hit["wood_heat"] else 0                                # 15
    sv["shelter"] = (9 if hit["second_dwelling"] else 0) + (6 if hit["barn"] else 0)  # 15
    sv["seclusion"] = 10 if hit["seclusion"] else 0                              # 10
    sv["reach"] = 0 if d is None else (15 if d < 1.5 else 11 if d < 2.0 else 7 if d <= 2.5 else 0)  # 15
    survival = sum(sv.values())

    # --- investment --------------------------------------------------------
    inv = {}
    pph = l.get("price_per_ha")
    if pph and median_price_per_ha:
        r = pph / median_price_per_ha
        inv["price"] = 30 if r < 0.6 else 22 if r < 1.0 else 12 if r < 1.5 else 4
    else:
        inv["price"] = 10
    inv["land_value"] = (15 if forest == 2 else 8 if forest == 1 else 0) + (10 if hit["arable"] else 0)  # 25
    inv["condition"] = round(cond * 2.5)                                          # 25
    inv["location"] = 0 if d is None else (15 if d < 1.5 else 11 if d < 2.0 else 7 if d <= 2.5 else 0)  # 15
    inv["market"] = int(CFG.get("region_liquidity", {}).get(l.get("region"), 3))   # 5
    invest = sum(inv.values())

    # --- motivations -------------------------------------------------------
    good, gaps = [], []
    if hit["well"]:
        good.append(_phrase(lang, "own well", "egen brunn"))
    else:
        gaps.append(_phrase(lang, "no well stated", "ingen brunn nämnd"))
    if hit["water"]:
        good.append(_phrase(lang, "lake or stream", "sjö eller bäck"))
    if forest == 2:
        good.append(_phrase(lang, f"{ha:g} ha with forest for firewood", f"{ha:g} ha med skog för ved"))
    elif forest == 1:
        good.append(_phrase(lang, "some forest", "viss skog"))
    else:
        gaps.append(_phrase(lang, "little or no forest", "lite eller ingen skog"))
    if hit["arable"]:
        good.append(_phrase(lang, "arable or pasture", "åker eller bete"))
    if hit["wood_heat"]:
        good.append(_phrase(lang, "wood heating installed", "vedeldning finns"))
    else:
        gaps.append(_phrase(lang, "no wood heating stated", "ingen vedeldning nämnd"))
    if hit["second_dwelling"]:
        good.append(_phrase(lang, "second dwelling", "extra bostad"))
    if hit["barn"]:
        good.append(_phrase(lang, "barn or workshop", "ladugård eller verkstad"))
    if hit["seclusion"]:
        good.append(_phrase(lang, "secluded position", "avskilt läge"))
    if d is not None:
        (good if d <= 2.5 else gaps).append(_phrase(lang, f"{d:g} h from {CFG['base']['name']}",
                                                    f"{d:g} h från {CFG['base']['name']}"))
    l["survival_why"] = (", ".join(good[:5]) or _phrase(lang, "nothing confirmed in the text", "inget bekräftat i texten"))
    if gaps:
        l["survival_why"] += _phrase(lang, ". Missing: ", ". Saknas: ") + ", ".join(gaps[:2]) + "."
    else:
        l["survival_why"] += "."

    ipart = []
    if pph and median_price_per_ha:
        rel = pph / median_price_per_ha
        word = (_phrase(lang, "well below", "klart under") if rel < 0.6 else
                _phrase(lang, "below", "under") if rel < 1.0 else
                _phrase(lang, "above", "över") if rel < 1.5 else _phrase(lang, "well above", "klart över"))
        pph_s = f"{pph:,.0f}".replace(",", "\u00a0")
        med_s = f"{median_price_per_ha:,.0f}".replace(",", "\u00a0")
        ipart.append(_phrase(lang, f"{pph_s} kr per ha, {word} the {med_s} kr median",
                             f"{pph_s} kr per ha, {word} medianen {med_s} kr"))
    if forest:
        ipart.append(_phrase(lang, "forest holds its value", "skogen håller värdet"))
    if inv["condition"] >= 18:
        ipart.append(_phrase(lang, "house needs little money", "huset kräver lite pengar"))
    elif inv["condition"] <= 8:
        ipart.append(_phrase(lang, "condition is a capex risk", "skicket är en kostnadsrisk"))
    if y:
        ipart.append(_phrase(lang, f"built {y}", f"byggår {y}"))
    ipart.append(_phrase(lang, f"{l.get('region') or 'unknown area'} resells {'well' if inv['market'] >= 4 else 'steadily'}",
                         f"{l.get('region') or 'okänt område'} säljs {'lätt vidare' if inv['market'] >= 4 else 'stadigt vidare'}"))
    l["invest_why"] = ", ".join(ipart[:4]) + "."

    l["signals"] = [k for k, v in hit.items() if v]
    l["survival_parts"] = sv
    l["invest_parts"] = inv
    l["survival_score"] = survival
    l["invest_score"] = invest
    l["score_parts"] = {**{f"sv_{k}": v for k, v in sv.items()}, **{f"in_{k}": v for k, v in inv.items()}}
    l["score"] = round((survival + invest) / 2)
    return l["score"]


def rescore_only():
    """Recompute scores from cached details without scraping (after criteria changes)."""
    cur = load_json(DATA / "listings.json", {"listings": []})
    details = load_json(DATA / "details.json", {})
    matched = cur.get("listings", [])
    pphs = [l["price_per_ha"] for l in matched if l.get("price_per_ha")]
    med_pph = statistics.median(pphs) if pphs else None
    for l in matched:
        if not l.get("image") and details.get(l["id"], {}).get("image"):
            l["image"] = details[l["id"]]["image"]
        score(l, details.get(l["id"], {}).get("text", ""), med_pph)
    matched.sort(key=lambda x: (-x["score"], x["price"]))
    cur["listings"] = matched
    cur["generated"] = datetime.datetime.now().isoformat(timespec="minutes")
    save_json(DATA / "listings.json", cur)
    dig = load_json(DATA / "digest_input.json", {})
    changes = dig.get("changes", {})
    top = matched[:15]
    lowmaint = [l for l in matched if (l.get("build_year") or 0) >= 1965 or l["score_parts"].get("maintenance", 0) >= 8][:20]
    pick_ids = {l["id"] for l in top} | {l["id"] for l in lowmaint} | {c["id"] for c in changes.get("price_changes", [])} | {n["id"] for n in changes.get("new", [])}
    digest = []
    for l in matched:
        if l["id"] in pick_ids:
            d = {k: l.get(k) for k in ("id", "title", "kommun", "region", "price", "land_ha", "living_m2",
                                        "rooms", "type", "url", "alt_url", "drive_h", "price_per_ha", "score",
                                        "score_parts", "signals", "first_seen", "days_tracked", "price_history",
                                        "broker", "days_text", "build_year", "survival_score", "invest_score",
                                        "survival_why", "invest_why")}
            d["description"] = (details.get(l["id"], {}).get("text", "") or l.get("teaser") or "")[:1500]
            digest.append(d)
    dig["listings"] = digest
    save_json(DATA / "digest_input.json", dig)
    log(f"rescored {len(matched)} listings; top: " + ", ".join(f"{l['title']} {l['score']}" for l in matched[:5]))


def refresh_details():
    """(Re)fetch detail text for listings whose cached text predates the facts
    extraction (no FAKTA block), then rescore. Used once after the 2026-09-17
    maintenance criteria; the daily run only fetches never-seen listings."""
    cur = load_json(DATA / "listings.json", {"listings": []})
    details = load_json(DATA / "details.json", {})
    force = "all" in sys.argv
    todo = [l for l in cur.get("listings", [])
            if force or "FAKTA" not in details.get(l["id"], {}).get("text", "")]
    log(f"refreshing {len(todo)} detail pages")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i, l in enumerate(todo, 1):
            try:
                txt = fetch_detail(browser, l)
                if re.search(r"såld eller borttagen|annonsen är borttagen|objektet är sålt|"
                             r"är inte längre till salu|^slutpris|\bslutpris\b.{0,40}\bkr\b|"
                             r"är såld|lagfart utfärdades", txt, re.I):
                    l["stale"] = True
                details[l["id"]] = {"text": txt, "fetched": TODAY, "stale": bool(l.get("stale"))}
                if l.get("image"):
                    details[l["id"]]["image"] = l["image"]
            except Exception as e:
                details[l["id"]] = {"text": details.get(l["id"], {}).get("text", ""), "fetched": TODAY, "error": str(e)[:200]}
            if i % 10 == 0:
                log(f"  details {i}/{len(todo)}")
                save_json(DATA / "details.json", details)
        browser.close()
    save_json(DATA / "details.json", details)
    rescore_only()


# ---------- main ----------

def main():
    prev = load_json(DATA / "listings.json", {"listings": []})
    prev_by_key = {}
    for l in prev.get("listings", []):
        l.setdefault("key", stable_key(l))
        prev_by_key.setdefault(l["key"], l)
    seen = load_json(DATA / "seen.json", {})
    # migrate seen.json from source ids to stable keys (keeps the earliest first_seen)
    if seen and not seen.get("_keyed"):
        id_to_key = {l["id"]: l["key"] for l in prev.get("listings", [])}
        migrated = {"_keyed": True}
        for sid, rec in seen.items():
            if sid.startswith("_"):
                continue
            k = id_to_key.get(sid) or stable_key({"kommun": rec.get("kommun"), "title": rec.get("title"), "price": (rec.get("prices") or [0])[-1]})
            cur = migrated.get(k)
            if not cur or rec.get("first_seen", "9999") < cur.get("first_seen", "9999"):
                rec["ids"] = sorted(set((cur or {}).get("ids", []) + [sid]))
                migrated[k] = rec
            else:
                cur["ids"] = sorted(set(cur.get("ids", []) + [sid]))
        seen = migrated
    seen.setdefault("_keyed", True)
    details = load_json(DATA / "details.json", {})

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Booli is the primary source (aggregates most broker listings and is
        # not bot-challenged). Hemnet sits behind Cloudflare and is best-effort.
        boo, boo_total = [], {}
        for name, u in BOOLI_SEARCHES.items():
            part, tot = scrape_booli(browser, u)
            boo += part
            boo_total[name] = tot
        hem, hem_total, hemnet_ok = [], {}, True
        for name, u in HEMNET_SEARCHES.items():
            for attempt in (1, 2):
                try:
                    part, tot = scrape_hemnet(browser, u)
                    hem += part
                    hem_total[name] = tot
                    break
                except Exception as e:
                    log(f"hemnet {name} attempt {attempt} failed: {str(e)[:120]}")
                    if attempt == 1:
                        time.sleep(60)  # Cloudflare usually relents after a pause
                    else:
                        hemnet_ok = False
                        log(f"hemnet {name} skipped for today")
        raw, seen_ids = [], set()
        for l in hem + boo:  # pages shift while paging, so the same id can appear twice
            if l["id"] not in seen_ids:
                seen_ids.add(l["id"])
                raw.append(l)
        matched = [l for l in raw if passes(l)]
        matched = dedupe(matched)
        log(f"raw {len(raw)} (hemnet {len(hem)}, booli {len(boo)}), matched after filter+dedupe {len(matched)}")

        # detail pages for listings without a cached description
        # refetch descriptions older than a week: Booli turns a sold listing
        # into a "Slutpris" page without removing it from the for-sale search,
        # so a stale cache keeps sold farms on the list (seen 2026-09-20).
        stale_before = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        todo = [l for l in matched if l["id"] not in details][:DETAIL_LIMIT]
        room = DETAIL_LIMIT - len(todo)
        if room > 0:
            old_cache = [l for l in matched
                         if l["id"] in details and details[l["id"]].get("fetched", "") < stale_before]
            old_cache.sort(key=lambda l: details[l["id"]].get("fetched", ""))
            todo += old_cache[:room]
        log(f"fetching {len(todo)} detail pages")
        for i, l in enumerate(todo, 1):
            try:
                txt = fetch_detail(browser, l)
                if re.search(r"såld eller borttagen|annonsen är borttagen|objektet är sålt|"
                             r"är inte längre till salu|^slutpris|\bslutpris\b.{0,40}\bkr\b|"
                             r"är såld|lagfart utfärdades", txt, re.I):
                    l["stale"] = True
                details[l["id"]] = {"text": txt, "fetched": TODAY, "stale": bool(l.get("stale"))}
                if l.get("image"):
                    details[l["id"]]["image"] = l["image"]
            except Exception as e:  # keep going, the card teaser still scores
                details[l["id"]] = {"text": "", "fetched": TODAY, "error": str(e)[:200]}
            if i % 10 == 0:
                log(f"  details {i}/{len(todo)}")
        browser.close()

    save_json(DATA / "details.json", details)
    stale = [l for l in matched if l.get("stale") or details.get(l["id"], {}).get("stale")]
    if stale:
        log(f"dropping {len(stale)} sold/removed records: " + ", ".join(l["title"] or l["id"] for l in stale[:8]))
        matched = [l for l in matched if l not in stale]

    # derived fields
    for l in matched:
        l["drive_h"] = drive_hours(l.get("kommun"), l.get("lat"), l.get("lon"))
        l["price_per_ha"] = round(l["price"] / l["land_ha"]) if l.get("land_ha") else None
        l["key"] = stable_key(l)
        rec = seen.get(l["key"])
        if rec:
            l["first_seen"] = rec["first_seen"]
            if rec["prices"][-1] != l["price"]:
                rec["prices"].append(l["price"])
                rec["price_dates"].append(TODAY)
            rec["ids"] = sorted(set(rec.get("ids", []) + [l["id"]]))
            rec.pop("gone", None)
        else:
            seen[l["key"]] = rec = {"first_seen": TODAY, "prices": [l["price"]], "price_dates": [TODAY],
                                    "title": l.get("title"), "kommun": l.get("kommun"), "ids": [l["id"]]}
            l["first_seen"] = TODAY
        l["price_history"] = list(zip(rec["price_dates"], rec["prices"]))
        l["days_tracked"] = (datetime.date.today() - datetime.date.fromisoformat(l["first_seen"])).days
    for l in matched:
        l["last_seen"] = TODAY

    pphs = [l["price_per_ha"] for l in matched if l.get("price_per_ha")]
    med_pph = statistics.median(pphs) if pphs else None
    for l in matched:
        if not l.get("image") and details.get(l["id"], {}).get("image"):
            l["image"] = details[l["id"]]["image"]
        score(l, details.get(l["id"], {}).get("text", ""), med_pph)
    matched.sort(key=lambda x: (-x["score"], x["price"]))

    # changes vs previous run
    cur_keys = {l["key"] for l in matched}
    # a price change also changes the key, so match previous entries by kommun+title too
    prev_by_kt = {k.rsplit("|", 1)[0]: v for k, v in prev_by_key.items()}
    new, price_changes = [], []
    for l in matched:
        if l["key"] in prev_by_key:
            continue
        old = prev_by_kt.get(l["key"].rsplit("|", 1)[0])
        if old and old.get("price") and old["price"] != l["price"]:
            price_changes.append({"id": l["id"], "title": l["title"], "kommun": l["kommun"],
                                  "old": old["price"], "new": l["price"], "url": l["url"]})
            # carry history over from the old key
            old_rec = seen.get(old["key"])
            if old_rec and old_rec is not seen.get(l["key"]):
                cur_rec = seen[l["key"]]
                cur_rec["first_seen"] = min(cur_rec["first_seen"], old_rec["first_seen"])
                cur_rec["prices"] = old_rec["prices"] + [l["price"]]
                cur_rec["price_dates"] = old_rec["price_dates"] + [TODAY]
                l["first_seen"] = cur_rec["first_seen"]
                seen.pop(old["key"], None)
        else:
            new.append(l)
    cur_kt = {k.rsplit("|", 1)[0] for k in cur_keys}
    gone = [v for k, v in prev_by_key.items() if k not in cur_keys and k.rsplit("|", 1)[0] not in cur_kt]
    for g in gone:
        seen.setdefault(g["key"], {}).update({"gone": TODAY})
    changes = {
        "date": TODAY,
        "new": [{"id": l["id"], "title": l["title"], "kommun": l["kommun"], "price": l["price"],
                 "land_ha": l.get("land_ha"), "score": l["score"], "url": l["url"]} for l in new],
        "gone": [{"id": g["id"], "title": g.get("title"), "kommun": g.get("kommun"), "price": g.get("price"),
                  "url": g.get("url"), "days_tracked": g.get("days_tracked")} for g in gone],
        "price_changes": price_changes,
        "first_run": not prev.get("listings"),
    }

    # stats
    prices = [l["price"] for l in matched]
    by_region = {}
    for l in matched:
        r = by_region.setdefault(l["region"], {"count": 0, "prices": [], "new": 0})
        r["count"] += 1
        r["prices"].append(l["price"])
        if l["id"] in {n["id"] for n in new}:
            r["new"] += 1
    for r in by_region.values():
        r["median_price"] = int(statistics.median(r["prices"])) if r["prices"] else None
        del r["prices"]
    stats = {
        "date": TODAY,
        "matched": len(matched),
        "new": len(new),
        "gone": len(gone),
        "price_cuts": sum(1 for c in price_changes if c["new"] < c["old"]),
        "price_rises": sum(1 for c in price_changes if c["new"] > c["old"]),
        "median_price": int(statistics.median(prices)) if prices else None,
        "median_price_per_ha": int(med_pph) if med_pph else None,
        "national_in_band": {"hemnet": hem_total, "booli": boo_total},
        "hemnet_ok": hemnet_ok,
        "by_region": by_region,
    }

    save_json(DATA / "listings.json", {"generated": datetime.datetime.now().isoformat(timespec="minutes"),
                                       "config": {k: CFG[k] for k in ("price_min", "price_max", "land_min_ha")},
                                       "stats": stats, "listings": matched})
    save_json(DATA / "changes.json", changes)
    save_json(DATA / "seen.json", seen)
    save_json(HIST / f"{TODAY}.json", {"date": TODAY, "stats": stats,
                                        "ids": [(l["id"], l["price"], l["score"]) for l in matched]})

    # compact input for the Claude step
    top = matched[:15]
    # the keyword pre-score is weak on maintenance, so always show Claude the
    # modern or renovated houses too (build year 1965+ or maintenance >= 8)
    lowmaint = [l for l in matched if (l.get("build_year") or 0) >= 1965 or l["score_parts"].get("maintenance", 0) >= 8][:20]
    pick_ids = {l["id"] for l in top} | {l["id"] for l in lowmaint} | {n["id"] for n in new} | {c["id"] for c in price_changes}
    digest = []
    for l in matched:
        if l["id"] in pick_ids:
            d = {k: l.get(k) for k in ("id", "title", "kommun", "region", "price", "land_ha", "living_m2",
                                        "rooms", "type", "url", "alt_url", "drive_h", "price_per_ha", "score",
                                        "score_parts", "signals", "first_seen", "days_tracked", "price_history",
                                        "broker", "days_text", "build_year", "survival_score", "invest_score",
                                        "survival_why", "invest_why")}
            d["description"] = (details.get(l["id"], {}).get("text", "") or l.get("teaser") or "")[:1500]
            digest.append(d)
    save_json(DATA / "digest_input.json", {"date": TODAY, "stats": stats, "changes": changes, "listings": digest})
    log(f"done: {len(matched)} matched, {len(new)} new, {len(gone)} gone, {len(price_changes)} price changes")


if __name__ == "__main__":
    if "--rescore" in sys.argv:
        rescore_only()
        sys.exit(0)
    if "--details" in sys.argv:
        refresh_details()
        sys.exit(0)
    try:
        main()
        (DATA / "scan_failed.txt").unlink(missing_ok=True)
    except Exception as e:
        (DATA / "scan_failed.txt").write_text(f"{datetime.datetime.now():%F %T} {type(e).__name__}: {e}\n")
        log(f"FAILED: {e}")
        sys.exit(1)
