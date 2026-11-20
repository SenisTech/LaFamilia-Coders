#!/usr/bin/env python3
"""Convert Sofia's official GTFS feed to data/sofia.json (no dependencies).
Usage: python3 build_sofia.py [URL-or-path-to-gtfs.zip]
Get the feed link from https://www.sofiatraffic.bg/bg/info-center/gtfs-danni"""
import collections, csv, io, json, os, sys, urllib.request, zipfile

SRC = sys.argv[1] if len(sys.argv) > 1 else "https://gtfs.sofiatraffic.bg/api/v1/static"  # unverified default

if SRC.startswith("http"):
    req = urllib.request.Request(SRC, headers={"User-Agent": "transit-map/0.1"})
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=180).read()))
else:
    z = zipfile.ZipFile(SRC)

def rows(name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))

routes = {r["route_id"]: r for r in rows("routes.txt")}
stops = {s["stop_id"]: s for s in rows("stops.txt")}

trips, count = {}, collections.Counter()
for t in rows("trips.txt"):
    k = (t["route_id"], t.get("direction_id") or "0", t.get("shape_id", ""))
    trips[t["trip_id"]] = k
    count[k] += 1

best = {}  # (route, direction) -> most common (route, dir, shape)
for k, c in count.items():
    if (k[0], k[1]) not in best or c > count[best[(k[0], k[1])]]:
        best[(k[0], k[1])] = k
wanted = set(best.values())

rep = {}  # one representative trip per wanted variant
for tid, k in trips.items():
    if k in wanted and k not in rep:
        rep[k] = tid
by_trip = {v: k for k, v in rep.items()}

seq = collections.defaultdict(list)
for st in rows("stop_times.txt"):
    k = by_trip.get(st["trip_id"])
    if k:
        seq[k].append((int(st["stop_sequence"]), st["stop_id"]))

shape_ids = {k[2] for k in wanted if k[2]}
pts = collections.defaultdict(list)
if "shapes.txt" in z.namelist():
    for p in rows("shapes.txt"):
        if p["shape_id"] in shape_ids:
            pts[p["shape_id"]].append((int(p["shape_pt_sequence"]), float(p["shape_pt_lat"]), float(p["shape_pt_lon"])))

out = []
for k in sorted(wanted):
    r = routes[k[0]]
    ss = [[stops[sid]["stop_name"], round(float(stops[sid]["stop_lat"]), 5), round(float(stops[sid]["stop_lon"]), 5)]
          for _, sid in sorted(seq[k])]
    line = [[round(a, 5), round(b, 5)] for _, a, b in sorted(pts.get(k[2], []))] or [[s[1], s[2]] for s in ss]
    out.append({"id": r["route_id"], "name": r["route_short_name"], "long": r.get("route_long_name", ""),
                "type": int(r["route_type"]), "color": "#" + (r.get("route_color") or "666666"),
                "dir": k[1], "line": line, "stops": ss})

os.makedirs("data", exist_ok=True)
with open("data/sofia.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"{len(out)} route directions written to data/sofia.json")