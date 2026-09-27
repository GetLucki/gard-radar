#!/usr/bin/env python3
"""Merge the daily judgement into the persistent board.

The board (data/board.json) is the ranked shortlist the site and the email show.
It survives between runs: an entry that was judged on an earlier day keeps its
text word for word, so the reading experience is stable and only genuinely new
listings change. Each run the Claude step judges ONLY the new candidates and
writes data/new_judgements.json; this script merges them in.

Rules:
  - new judgements are inserted, ranked by score
  - existing entries keep their wording, only facts (price, days) are refreshed
  - entries whose listing is gone are dropped and listed in `dropped`
  - the board is capped at BOARD_MAX entries
  - `added_on` marks when an entry entered the board; the site and email badge
    everything added in the latest run as new
"""
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
BOARD_MAX = int(json.load(open(ROOT / "config.json", encoding="utf-8")).get("board_max", 50))
TODAY = datetime.date.today().isoformat()


def load(name, default):
    try:
        return json.load(open(DATA / name, encoding="utf-8"))
    except Exception:
        return default


def save(name, obj):
    with open(DATA / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def main():
    listings = load("listings.json", {"listings": [], "stats": {}})
    board = load("board.json", {"entries": [], "history": []})
    fresh = load("new_judgements.json", {})

    by_id = {}
    for l in listings.get("listings", []):
        by_id[l["id"]] = l
        for a in l.get("alt_ids", []) or []:
            by_id[a] = l
        if l.get("key"):
            by_id.setdefault("key:" + l["key"], l)

    def find(entry):
        return (by_id.get(entry.get("id"))
                or by_id.get("key:" + (entry.get("key") or ""))
                or next((l for l in listings.get("listings", [])
                         if l["url"] == entry.get("url") or l.get("alt_url") == entry.get("url")), None))

    entries, dropped = [], []
    for e in board.get("entries", []):
        l = find(e)
        if not l:
            dropped.append({"title": e.get("title"), "kommun": e.get("kommun"),
                            "why": "no longer listed", "date": TODAY})
            continue
        # keep the judgement text; refresh the facts that move
        e.update({
            "id": l["id"], "key": l.get("key"), "url": l["url"], "price": l["price"],
            "land_ha": l.get("land_ha"), "living_m2": l.get("living_m2"),
            "build_year": l.get("build_year"), "drive_h": l.get("drive_h"),
            "kommun": l.get("kommun"), "region": l.get("region"),
            "score": l.get("score"), "survival_score": l.get("survival_score"),
            "invest_score": l.get("invest_score"), "days_tracked": l.get("days_tracked"),
        })
        e.setdefault("added_on", board.get("date") or TODAY)
        entries.append(e)

    known = {e["id"] for e in entries} | {e.get("key") for e in entries}
    added = 0
    for j in fresh.get("entries", []) or []:
        l = by_id.get(j.get("id")) or next(
            (x for x in listings.get("listings", []) if x["url"] == j.get("url")), None)
        if not l or l["id"] in known or l.get("key") in known:
            continue
        entries.append({
            "id": l["id"], "key": l.get("key"), "title": l.get("title"), "url": l["url"],
            "kommun": l.get("kommun"), "region": l.get("region"), "price": l["price"],
            "land_ha": l.get("land_ha"), "living_m2": l.get("living_m2"),
            "build_year": l.get("build_year"), "drive_h": l.get("drive_h"),
            "score": l.get("score"), "survival_score": l.get("survival_score"),
            "invest_score": l.get("invest_score"), "days_tracked": l.get("days_tracked"),
            "prepping_why": j.get("prepping_why", ""), "invest_why": j.get("invest_why", ""),
            "rank_why": j.get("rank_why", ""), "maintenance": j.get("maintenance", ""),
            "recommendation": j.get("recommendation", ""),
            "added_on": TODAY, "judged_on": TODAY,
        })
        known.add(l["id"])
        added += 1

    entries.sort(key=lambda e: (-(e.get("score") or 0), e.get("price") or 0))
    cut = entries[BOARD_MAX:]
    entries = entries[:BOARD_MAX]
    for e in cut:
        dropped.append({"title": e.get("title"), "kommun": e.get("kommun"),
                        "why": f"pushed out of the top {BOARD_MAX}", "date": TODAY})

    out = {
        "date": TODAY,
        "market_summary": fresh.get("market_summary") or board.get("market_summary", ""),
        "added_today": [e["id"] for e in entries if e.get("added_on") == TODAY],
        "dropped": dropped,
        "criteria_changes": fresh.get("criteria_changes", []),
        "entries": entries,
        "history": (board.get("history", []) + [{"date": TODAY, "added": added,
                                                 "dropped": len(dropped), "size": len(entries)}])[-30:],
    }
    save("board.json", out)

    # the site and email still read recommendations.json: the top three of the board
    save("recommendations.json", {
        "date": TODAY,
        "market_summary": out["market_summary"],
        "top": entries,
        "dropped": dropped,
        "criteria_changes": out["criteria_changes"],
        "added_today": out["added_today"],
    })
    print(f"board: {len(entries)} entries, {added} added today, {len(dropped)} dropped")


if __name__ == "__main__":
    sys.exit(main())
