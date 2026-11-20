#!/usr/bin/env python3
"""Static file server + live vehicle API. pip install gtfs-realtime-bindings
Run: python3 server.py [port]   (live is simply disabled if the library is missing)"""
import http.server, json, sys, time, urllib.request
from urllib.parse import urlparse
try:
    from google.transit import gtfs_realtime_pb2
except ImportError:
    gtfs_realtime_pb2 = None
    print("gtfs-realtime-bindings not installed: live vehicles disabled")

CITIES = json.load(open("cities.json", encoding="utf-8"))
RT = {c["id"]: c["realtime"] for c in CITIES if c.get("realtime")} if gtfs_realtime_pb2 else {}
cache = {}

def vehicles(cid):
    now = time.time()
    if cid in cache and now - cache[cid][0] < 8:
        return cache[cid][1]
    req = urllib.request.Request(RT[cid], headers={"User-Agent": "transit-map/0.2"})
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(urllib.request.urlopen(req, timeout=15).read())
    out = []
    for e in feed.entity:
        if not e.HasField("vehicle") or not e.vehicle.HasField("position"):
            continue
        v = e.vehicle
        out.append({"id": v.vehicle.id or e.id, "route": v.trip.route_id,
                    "lat": v.position.latitude, "lon": v.position.longitude,
                    "bearing": v.position.bearing if v.position.HasField("bearing") else None,
                    "ts": v.timestamp or feed.header.timestamp})
    cache[cid] = (now, out)
    return out

class H(http.server.SimpleHTTPRequestHandler):
    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); p = u.path
        if p in ("/intmap", "/intmap/"):          # the map lives at /intmap (file: intmap.html); "/" is the homepage (index.html)
            if p.endswith("/"):
                self.send_response(301); self.send_header("Location", "/intmap" + ("?" + u.query if u.query else "")); self.end_headers(); return
            self.path = "/intmap.html" + ("?" + u.query if u.query else "")
            return super().do_GET()
        if p == "/api/capabilities":
            return self.send_json({"live": list(RT)})
        if p.startswith("/api/vehicles/"):
            cid = p.rsplit("/", 1)[1]
            if cid not in RT:
                return self.send_json({"error": "no live data"}, 404)
            try:
                return self.send_json({"vehicles": vehicles(cid), "now": int(time.time())})
            except Exception as ex:
                return self.send_json({"error": str(ex)}, 502)
        return super().do_GET()

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
print(f"Homepage http://localhost:{port}   Map http://localhost:{port}/intmap   (phone on same Wi-Fi: http://<your-PC-IP>:{port})")
http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
