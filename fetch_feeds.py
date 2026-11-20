#!/usr/bin/env python3
"""Download GTFS zips into feeds/ from the Mobility Database (stable hosted copies).
One-time setup: make a free account at https://mobilitydatabase.org, copy your API *refresh token*,
then:  set MDB_REFRESH_TOKEN=<token>   (Windows)   /   export MDB_REFRESH_TOKEN=<token>  (Mac/Linux)
Usage:  python3 fetch_feeds.py          download missing cities
        python3 fetch_feeds.py --force  re-download all
        python3 fetch_feeds.py --list   just list every Bulgarian feed it can see
A city can be pinned with "mdb_id": "mdb-1234" in cities.json if the automatic match picks the wrong feed."""
import json, os, sys, urllib.request, urllib.parse

API = "https://api.mobilitydatabase.org/v1"
tok = os.environ.get("MDB_REFRESH_TOKEN")
if not tok:
    sys.exit("Set MDB_REFRESH_TOKEN first (see the top of this file).")

def call(path, data=None, token=None):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json", "User-Agent": "transit-map/0.3",
                 **({"Authorization": "Bearer " + token} if token else {})})
    return json.load(urllib.request.urlopen(req, timeout=60))

access = call("/tokens", {"refresh_token": tok})["access_token"]
feeds, off = [], 0
while True:
    page = call(f"/gtfs_feeds?country_code=BG&limit=100&offset={off}", token=access)
    if not page: break
    feeds += page; off += 100
    if len(page) < 100: break

def info(f):
    d = f.get("latest_dataset") or {}
    return f["id"], f.get("provider", "?"), d.get("hosted_url"), (d.get("downloaded_at") or "")

if "--list" in sys.argv:
    for f in feeds:
        i, p, u, t = info(f); print(i, "|", p, "|", t[:10], "|", "ok" if u else "no hosted copy")
    sys.exit()

def place_text(f):  # only provider name + declared locations (NOT routes/agencies of the whole feed)
    return (f.get("provider", "") + " " + json.dumps(f.get("locations") or [], ensure_ascii=False)).lower()

def geo_ok(f, c):  # reject multi-country / national feeds and feeds whose area misses the city
    if c.get("kind") == "rail":
        return True
    if any(l.get("country_code") not in (None, "BG") for l in (f.get("locations") or [])):
        return False
    bb = (f.get("latest_dataset") or {}).get("bounding_box") or {}
    try:
        cy, cx = c["center"]
        la0, la1 = bb["minimum_latitude"], bb["maximum_latitude"]
        lo0, lo1 = bb["minimum_longitude"], bb["maximum_longitude"]
        return la0 - .1 <= cy <= la1 + .1 and lo0 - .1 <= cx <= lo1 + .1 and (la1 - la0) < 1.2 and (lo1 - lo0) < 1.5
    except (KeyError, TypeError):
        return True

os.makedirs("feeds", exist_ok=True)
for c in json.load(open("cities.json", encoding="utf-8")):
    dest = f"feeds/{c['id']}.zip"
    if os.path.exists(dest) and "--force" not in sys.argv:
        print(f"= {c['id']}: already have it"); continue
    keys = [k.lower() for k in c.get("match", [])]
    if c.get("mdb_id"):
        cand = [f for f in feeds if f["id"] == c["mdb_id"]]
    else:
        cand = [f for f in feeds if any(k in place_text(f) for k in keys) and geo_ok(f, c)]
    cand = [f for f in cand if info(f)[2]]
    if not cand:
        print(f"- {c['id']}: no matching feed, skipped"); continue
    # best = provider name contains the city keyword, then newest
    cand.sort(key=lambda f: (any(k in f.get("provider", "").lower() for k in keys), info(f)[3]), reverse=True)
    i, p, u, t = info(cand[0])
    if len(cand) > 1:
        print(f"  {c['id']}: {len(cand)} candidates: " + "; ".join(f"{info(f)[0]} {info(f)[1]}" for f in cand[:4]))
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "transit-map/0.3"})
        open(dest, "wb").write(urllib.request.urlopen(req, timeout=180).read())
        print(f"+ {c['id']}: {i} ({p}) -> {dest}")
    except Exception as e:
        print(f"- {c['id']}: download failed ({e})")
