/* Timetable-based journey planner (RAPTOR). Works in the browser (window.Planner) and Node (module.exports). */
(function (g) {
  const WALK = 1.25, DETOUR = 1.3, MINX = 120, FOOT = 400, LIM = 20 * 3600, ACCESS = 2000, FOOT_RAIL = 800, RAIL_ACCESS = 6000;
  const rad = Math.PI / 180;
  const dist = (a, b) => { const x = (b[0] - a[0]) * rad, y = (b[1] - a[1]) * rad,
    h = Math.sin(x / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(y / 2) ** 2; return 12742000 * Math.asin(Math.sqrt(h)); };

  /* sets: [{id, kind:'rail'|'city'|..., routes:[{id,dir,name,color,k,stops:[[name,lat,lon]],line}], sched:{"id|dir":{a,d,t}}|null}] */
  function prepare(sets) {
    const stops = [], idx = new Map(), routes = [], sr = [];
    const sid = (d, s) => { const k = d.id + '|' + s[1] + '|' + s[2]; let i = idx.get(k);
      if (i === undefined) { i = stops.length; idx.set(k, i); stops.push({ n: s[0], p: [s[1], s[2]], ds: d.id, rail: d.kind === 'rail' }); sr.push([]); } return i; };
    for (const d of sets) {
      if (!d.sched) continue;
      for (const r of d.routes) {
        const sc = d.sched[r.id + '|' + r.dir];
        if (!sc || !sc.t || !sc.a || sc.a.length !== r.stops.length) continue;
        const ri = routes.length, st = r.stops.map(s => sid(d, s));
        routes.push({ ds: d.id, r, st, a: sc.a, d: sc.d, t: sc.t });
        st.forEach((s, p) => sr[s].push([ri, p]));
      }
    }
    const G = 0.01, grid = new Map(), ck = (x, y) => x + ',' + y;
    stops.forEach((s, i) => { const k = ck(Math.floor(s.p[0] / G), Math.floor(s.p[1] / G)); (grid.get(k) || grid.set(k, []).get(k)).push(i); });
    const foot = stops.map((s, i) => { const cx = Math.floor(s.p[0] / G), cy = Math.floor(s.p[1] / G), o = [];
      for (let x = cx - 1; x <= cx + 1; x++) for (let y = cy - 1; y <= cy + 1; y++)
        for (const j of grid.get(ck(x, y)) || []) { if (j === i) continue; const m = dist(s.p, stops[j].p); if (m <= ((s.rail || stops[j].rail) ? FOOT_RAIL : FOOT)) o.push([j, m * DETOUR / WALK]); }
      return o; });
    return { stops, routes, sr, foot };
  }

  function trips(rt, day) {
    if (rt._k === day) return rt._tr;
    const pick = (di, add) => { const o = []; for (const m in rt.t) if (m[di] === '1') for (const x of rt.t[m]) o.push(x + add); return o; };
    const a = pick(day, 0).concat(pick((day + 1) % 7, 86400)).sort((x, y) => x - y).filter((x, i, arr) => !i || x !== arr[i - 1]);
    rt._k = day; rt._tr = a; return a;
  }

  function near(net, p, R, n, pred) {
    const o = []; net.stops.forEach((s, i) => { if (Math.abs(s.p[0] - p[0]) * 111000 > R || (pred && !pred(s))) return; const m = dist(p, s.p); if (m <= R) o.push([i, m]); });
    return o.sort((a, b) => a[1] - b[1]).slice(0, n).map(([i, m]) => [i, m * DETOUR / WALK]);
  }

  function raptor(net, src, dst, t0, day, banned, K) {
    const N = net.stops.length, INF = 1e12, R = net.routes, best = new Float64Array(N).fill(INF);
    const tau = [], par = [], rd = [], ends = [];
    let T = new Float64Array(N).fill(INF), RD = new Uint8Array(N), P = new Map(), marked = new Set();
    const relax = (set) => { const add = new Set(); for (const p of set) for (const [q, sec] of net.foot[p]) { const t = T[p] + sec;
      if (t < T[q] && t < best[q] && t < t0 + LIM) { T[q] = t; best[q] = t; RD[q] = 0; P.set(q, { f: p, sec }); add.add(q); } } return add; };
    for (const [s, w] of src) if (t0 + w < T[s]) { T[s] = t0 + w; best[s] = T[s]; P.set(s, { a: 1, w }); marked.add(s); }
    for (const q of relax(marked)) marked.add(q);
    tau.push(T); par.push(P); rd.push(RD);
    let bestDest = INF;
    for (let k = 1; k <= K; k++) {
      const pT = tau[k - 1], pRD = rd[k - 1];
      T = Float64Array.from(pT); RD = Uint8Array.from(pRD); P = new Map();
      const Q = new Map();
      for (const p of marked) for (const [r, pos] of net.sr[p]) { if (banned && banned.has(r)) continue; const q = Q.get(r); if (q === undefined || pos < q) Q.set(r, pos); }
      const nm = new Set();
      for (const [r, pos] of Q) {
        const rt = R[r], tr = trips(rt, day); if (!tr.length) continue;
        let cur = -1, bp = 0;
        for (let j = pos; j < rt.st.length; j++) {
          const s = rt.st[j];
          if (cur >= 0) { const arr = tr[cur] + rt.a[j];
            if (arr < best[s] && arr < t0 + LIM) { T[s] = arr; best[s] = arr; RD[s] = 1; P.set(s, { r, b: bp, j, tt: tr[cur] }); nm.add(s); } }
          const prev = pT[s];
          if (prev < INF) { const need = prev + (pRD[s] ? MINX : 0) - rt.d[j]; let lo = 0, hi = tr.length;
            while (lo < hi) { const m = (lo + hi) >> 1; if (tr[m] < need) lo = m + 1; else hi = m; }
            if (lo < tr.length && (cur < 0 || lo < cur)) { cur = lo; bp = j; } }
        }
      }
      for (const q of relax(nm)) nm.add(q);
      tau.push(T); par.push(P); rd.push(RD); marked = nm;
      let bd = INF, bs = -1; for (const [s, w] of dst) { const t = T[s] + w; if (t < bd) { bd = t; bs = s; } }
      if (bs >= 0 && bd < bestDest - 60) { bestDest = bd; ends.push({ k, s: bs, arr: bd, w: dst.find(x => x[0] === bs)[1] }); }
      if (!marked.size) break;
    }
    return { par, ends };
  }

  function journey(net, par, e, A, B, t0) {
    const R = net.routes, S = net.stops, legs = []; let s = e.s, kk = e.k, access = 0, p;
    for (;;) {
      p = null; while (kk >= 0 && !(p = par[kk].get(s))) kk--;
      if (!p) return null;
      if (p.a) { access = p.w; legs.unshift({ t: 'walk', sec: access, from: { n: '', p: A }, to: S[s] }); break; }
      if (p.f !== undefined) { legs.unshift({ t: 'walk', sec: p.sec, from: S[p.f], to: S[s] }); s = p.f; continue; }
      const rt = R[p.r];
      legs.unshift({ t: 'ride', ds: rt.ds, route: rt.r, name: rt.r.name, color: rt.r.color, k: rt.r.k, from: S[rt.st[p.b]], to: S[s],
        dep: p.tt + rt.d[p.b], arr: p.tt + rt.a[p.j], n: p.j - p.b, ri: p.r });
      s = rt.st[p.b]; kk--;
    }
    legs.push({ t: 'walk', sec: e.w, from: S[e.s], to: { n: '', p: B } });
    const rides = legs.filter(l => l.t === 'ride'); if (!rides.length) return null;
    const out = legs.filter(l => l.t === 'ride' || l.sec >= 45);
    return { legs: out, leave: rides[0].dep - access, arrive: e.arr, changes: rides.length - 1 };
  }

  const sig = j => j.legs.filter(l => l.t === 'ride').map(l => l.ri + ':' + l.from.p + '>' + l.to.p).join('|');

  const merge = (a, b) => { const m = new Map(a); for (const [i, w] of b) if (!m.has(i) || w < m.get(i)) m.set(i, w); return [...m]; };

  /* A, B: [lat,lon]; t0: seconds since midnight; day: 0=Mon..6=Sun. Returns up to 4 journeys, fastest first.
     o.inter = between-cities mode: also reaches rail stations up to 6 km away (bus stops would otherwise crowd them out) and allows one more change. */
  function search(net, A, B, t0, day, o) {
    o = o || {};
    let src = near(net, A, ACCESS, 25), dst = near(net, B, ACCESS, 25);
    if (o.inter) { const rail = s => s.rail; src = merge(src, near(net, A, RAIL_ACCESS, 6, rail)); dst = merge(dst, near(net, B, RAIL_ACCESS, 6, rail)); }
    if (!src.length || !dst.length) return [];
    const run = banned => { const { par, ends } = raptor(net, src, dst, t0, day, banned, o.inter ? 6 : 5);
      return ends.map(e => journey(net, par, e, A, B, t0)).filter(Boolean); };
    let all = run(null);
    if (!all.length) return [];
    all.sort((a, b) => a.arrive - b.arrive);
    const main = all[0].legs.filter(l => l.t === 'ride').sort((a, b) => (b.arr - b.dep) - (a.arr - a.dep)).slice(0, 2).map(l => l.ri);
    for (const r of main) all = all.concat(run(new Set([r])));
    const seen = new Set();
    return all.sort((a, b) => a.arrive - b.arrive || a.changes - b.changes).filter(j => { const s = sig(j); if (seen.has(s)) return false; seen.add(s); return true; }).slice(0, 4);
  }

  const api = { prepare, search, dist };
  if (typeof module !== 'undefined') module.exports = api; else g.Planner = api;
})(typeof window !== 'undefined' ? window : globalThis);
