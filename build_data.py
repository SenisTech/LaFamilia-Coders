#!/usr/bin/env python3
"""Build data/<city>.json (+ data/<city>.sched.json timetables) for every city in cities.json that has a feed.
A feed is taken from feeds/<id>.zip if present, otherwise downloaded from the
city's "url" (if any). Cities with no usable feed are skipped and never appear in the app.
Timetables: for each route+direction the most common stop pattern is kept; every trip with the same
first stop / last stop / stop count is treated as running on that pattern, with the representative
trip's per-stop time offsets. Weekly pattern only (calendar.txt); holiday exceptions are not applied.
Usage: python3 build_data.py [city-id ...]"""
import collections, csv, datetime, io, json, math, os, sys, urllib.request, zipfile

def open_zip(c):
    f = c.get("file")
    if f and os.path.exists(f):
        return zipfile.ZipFile(f)
    if c.get("url"):
        req = urllib.request.Request(c["url"], headers={"User-Agent": "transit-map/0.4"})
        return zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=180).read()))
    return None

def km(a, b):
    r = math.pi / 180
    x = math.sin((b[0]-a[0])*r/2)**2 + math.cos(a[0]*r)*math.cos(b[0]*r)*math.sin((b[1]-a[1])*r/2)**2
    return 12742 * math.asin(math.sqrt(x))

def local_only(routes, c):
    """Drop routes that are mostly outside the city area (wrong city / other country in the feed)."""
    if c.get("kind") == "rail":
        return routes
    rad = c.get("radius_km", 35)
    keep = [r for r in routes if sum(km(c["center"], s[1:]) <= rad for s in r["stops"]) >= 0.5 * len(r["stops"])]
    if len(keep) < len(routes):
        print(f"  {c['id']}: dropped {len(routes)-len(keep)} routes outside {rad} km of the city")
    return keep

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def hms(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        h, m, x = s.split(":")
        return int(h) * 3600 + int(m) * 60 + int(x)
    except ValueError:
        return None

def fill(v):
    """Interpolate None gaps (feeds that only give times at timing points)."""
    known = [i for i, x in enumerate(v) if x is not None]
    if not known:
        return None
    v = list(v)
    for i in range(len(v)):
        if v[i] is None:
            lo = max((j for j in known if j < i), default=None)
            hi = min((j for j in known if j > i), default=None)
            v[i] = v[hi] if lo is None else v[lo] if hi is None else v[lo] + (v[hi] - v[lo]) * (i - lo) / (hi - lo)
    return [int(round(x)) for x in v]

def build(z, c):
    names = z.namelist()
    def rows(name):
        with z.open(name) as fh:
            yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
    routes = {r["route_id"]: r for r in rows("routes.txt")}
    stops = {s["stop_id"]: s for s in rows("stops.txt")}

    # --- service calendar: service_id -> 7-char Mon..Sun mask ---
    mask, dates = {}, []
    if "calendar.txt" in names:
        for r in rows("calendar.txt"):
            mask[r["service_id"]] = "".join("1" if (r.get(d) or "0").strip() == "1" else "0" for d in DAYS)
            dates += [r.get("start_date", ""), r.get("end_date", "")]
    if "calendar_dates.txt" in names:
        add = collections.defaultdict(set)
        for r in rows("calendar_dates.txt"):
            d = (r.get("date") or "").strip(); dates.append(d)
            if r.get("exception_type") == "1" and len(d) == 8:
                add[r["service_id"]].add(datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday())
        for sid, wd in add.items():
            mask.setdefault(sid, "".join("1" if i in wd else "0" for i in range(7)))
    dates = sorted(d for d in dates if len(d) == 8 and d.isdigit())

    trips, count, svc = {}, collections.Counter(), {}
    for t in rows("trips.txt"):
        k = (t["route_id"], t.get("direction_id") or "0", t.get("shape_id", ""))
        trips[t["trip_id"]] = k
        svc[t["trip_id"]] = t.get("service_id", "")
        count[k] += 1
    best = {}
    for k, n in count.items():
        rd = (k[0], k[1])
        if rd not in best or n > count[best[rd]]:
            best[rd] = k
    wanted = set(best.values())
    rep = {}
    for tid, k in trips.items():
        if k in wanted and k not in rep:
            rep[k] = tid
    by_trip = {v: k for k, v in rep.items()}

    # one pass over stop_times: representative sequences + a (first stop, last stop, count, first time) signature per trip
    seq = collections.defaultdict(list)
    sig = {}
    for st in rows("stop_times.txt"):
        tid, q, sid = st["trip_id"], int(st["stop_sequence"]), st["stop_id"]
        arr, dep = hms(st.get("arrival_time")), hms(st.get("departure_time"))
        tm = dep if dep is not None else arr
        g = sig.get(tid)
        if g is None:
            sig[tid] = [q, sid, tm, q, sid, 1]
        else:
            g[5] += 1
            if q < g[0]: g[0], g[1], g[2] = q, sid, tm
            if q > g[3]: g[3], g[4] = q, sid
        k = by_trip.get(tid)
        if k:
            seq[k].append((q, sid, arr, dep))

    sh = {k[2] for k in wanted if k[2]}
    pts = collections.defaultdict(list)
    if "shapes.txt" in names:
        for p in rows("shapes.txt"):
            if p["shape_id"] in sh:
                pts[p["shape_id"]].append((int(p["shape_pt_sequence"]), float(p["shape_pt_lat"]), float(p["shape_pt_lon"])))

    # group all trips of the representative pattern by weekday mask
    repsig = {rd: (lambda g: (g[1], g[4], g[5]) if g else None)(sig.get(rep[k])) for rd, k in best.items()}
    starts = collections.defaultdict(lambda: collections.defaultdict(set))
    for tid, k in trips.items():
        rd = (k[0], k[1]); g = sig.get(tid)
        if g and g[2] is not None and (g[1], g[4], g[5]) == repsig.get(rd):
            starts[rd][mask.get(svc[tid], "1111111")].add(g[2])

    out, sched = [], {}
    for k in sorted(wanted):
        r = routes[k[0]]
        rows_ = [x for x in sorted(seq[k]) if x[1] in stops]
        if not rows_:
            continue
        ss = [[stops[x[1]]["stop_name"], round(float(stops[x[1]]["stop_lat"]), 5), round(float(stops[x[1]]["stop_lon"]), 5)] for x in rows_]
        line = [[round(a, 5), round(b, 5)] for _, a, b in sorted(pts.get(k[2], []))] or [[s[1], s[2]] for s in ss]
        name = (r.get("route_short_name") or r.get("route_long_name") or r["route_id"]).strip()
        out.append({"id": r["route_id"], "name": name, "long": r.get("route_long_name", ""),
                    "type": int(r.get("route_type") or 3), "color": "#" + (r.get("route_color") or "666666"),
                    "dir": k[1], "line": line, "stops": ss})
        arrs, deps = [x[2] for x in rows_], [x[3] for x in rows_]
        base = deps[0] if deps[0] is not None else arrs[0]
        A, D = fill(arrs), fill(deps)
        A, D = A or D, D or A
        t = {m: sorted(s) for m, s in starts[(k[0], k[1])].items() if s}
        if base is None and A:
            base = A[0]
        if A and t and base is not None:
            sched[f"{r['route_id']}|{k[1]}"] = {"a": [x - base for x in A], "d": [x - base for x in D], "t": t}

    # feed metadata shown to the user as "source"
    meta = {"built": datetime.date.today().isoformat(),
            "origin": c.get("url") or ("local file " + c["file"] if c.get("file") else ""),
            "start": dates[0] if dates else "", "end": dates[-1] if dates else ""}
    if "agency.txt" in names:
        a = next(iter(rows("agency.txt")), {})
        meta["agency"], meta["site"] = a.get("agency_name", ""), a.get("agency_url", "")
    if "feed_info.txt" in names:
        f = next(iter(rows("feed_info.txt")), {})
        meta["publisher"] = f.get("feed_publisher_name", "")
        meta["site"] = meta.get("site") or f.get("feed_publisher_url", "")
        meta["start"] = f.get("feed_start_date") or meta["start"]
        meta["end"] = f.get("feed_end_date") or meta["end"]
    return out, sched, meta

if __name__ == "__main__":
    cities = json.load(open("cities.json", encoding="utf-8"))
    only = set(sys.argv[1:])
    os.makedirs("data", exist_ok=True)
    built = []
    for c in cities:
        if only and c["id"] not in only:
            if os.path.exists(f"data/{c['id']}.json"): built.append(c)
            continue
        try:
            z = open_zip(c)
            if z is None:
                print(f"- {c['id']}: no feed yet, skipped"); continue
            data, sched, meta = build(z, c)
            data = local_only(data, c)
            if not data:
                print(f"- {c['id']}: feed had no usable routes, skipped"); continue
            keep = {r["id"] + "|" + r["dir"] for r in data}
            sched = {k: v for k, v in sched.items() if k in keep}
            json.dump(data, open(f"data/{c['id']}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            sp = f"data/{c['id']}.sched.json"
            if sched:
                sched["_meta"] = meta
                json.dump(sched, open(sp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            elif os.path.exists(sp):
                os.remove(sp)
            built.append(c); print(f"+ {c['id']}: {len(data)} route directions, {len(sched) - (1 if sched else 0)} with timetables")
        except Exception as e:
            print(f"- {c['id']}: failed ({e}), skipped")
    index = [{"id": c["id"], "name": c["name"], "center": c["center"], "zoom": c.get("zoom", 12),
              "kind": c.get("kind", "city"), "live": bool(c.get("realtime")),
              "sched": os.path.exists(f"data/{c['id']}.sched.json")} for c in built]
    json.dump(index, open("data/index.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"data/index.json: {len(index)} datasets available")
    print("total route directions:", sum(len(json.load(open(f"data/{c['id']}.json", encoding="utf-8"))) for c in built))
