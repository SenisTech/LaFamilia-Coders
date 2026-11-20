# Transit map v0.2 (Bulgaria)
1. Put each city's GTFS zip in `feeds/<id>.zip` (ids in cities.json). Sofia/Plovdiv can also download from their `url`.
   Most other cities: Bulgarian National Access Point, https://www.sipbg.gov.bg/bgnap (links change on every upload, so download manually).
2. `python3 build_data.py` – builds data/*.json; cities without a feed are skipped and never shown.
3. `pip install gtfs-realtime-bindings` (for live buses), then `python3 server.py` and open http://localhost:8000
   On a phone (same Wi-Fi): http://<PC-IP>:8000
