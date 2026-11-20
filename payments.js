/* Mock payment layer - CONCEPT ONLY. Nothing is charged, no card data is stored or sent anywhere.
   The UI (index.html) only talks to Payments.*. To go live, replace Payments.provider with an object
   that has the same method:  charge(order, method, details) -> Promise<{ref, ...}>  (throw {code:'declined'|'insufficient'|'invalid'} on failure)
   and move ticket issuing to your backend (server-signed QR codes, real validity rules, receipts, refunds). */
(function (g) {
  const LS = { get(k) { try { return localStorage.getItem(k) } catch (e) { return null } }, set(k, v) { try { localStorage.setItem(k, v) } catch (e) {} } };
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const rid = n => { const a = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; let s = ''; for (let i = 0; i < n; i++) s += a[Math.floor(Math.random() * a.length)]; return s; };
  const err = c => Object.assign(new Error(c), { code: c });
  const VALID = 2 * 3600 * 1000;               // demo rule: a ticket is valid 2 h after purchase
  const round2 = v => Math.round(v * 100) / 100;

  const wallet = {                              // fake in-app balance, starts at 20.00
    get() { const v = parseFloat(LS.get('demoWallet')); return isNaN(v) ? 20 : v; },
    set(v) { LS.set('demoWallet', String(round2(v))); },
    topup(v) { this.set(this.get() + v); }
  };
  const tickets = {                             // purchased demo tickets, newest first
    list() { try { return JSON.parse(LS.get('demoTickets') || '[]'); } catch (e) { return []; } },
    add(a) { LS.set('demoTickets', JSON.stringify(a.concat(this.list()).slice(0, 50))); },
    clear() { LS.set('demoTickets', '[]'); }
  };

  /* Deterministic fake QR (NOT scannable): same code -> same picture. */
  function qr(code) {
    const N = 25; let h = 2166136261;
    for (const c of String(code)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); }
    let s = h >>> 0; const rnd = () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
    let d = '';
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const fx = x < 7 ? x : x >= N - 7 ? x - (N - 7) : -1, fy = y < 7 ? y : y >= N - 7 ? y - (N - 7) : -1;
      let on;
      if ((x < 8 && y < 8) || (x >= N - 8 && y < 8) || (x < 8 && y >= N - 8)) {
        on = fx >= 0 && fy >= 0 && (fx === 0 || fx === 6 || fy === 0 || fy === 6 || (fx >= 2 && fx <= 4 && fy >= 2 && fy <= 4));
        rnd();
      } else on = rnd() > 0.5;
      if (on) d += 'M' + x + ' ' + y + 'h1v1h-1z';
    }
    return '<svg viewBox="0 0 ' + N + ' ' + N + '" shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg"><path d="' + d + '" fill="#000"/></svg>';
  }

  /* The mock "payment service provider". Replace this object for a real one. */
  const mock = {
    id: 'mock',
    async charge(order, method, d) {
      await wait(1200 + Math.random() * 600);
      const ref = 'mock_' + rid(10);
      if (method === 'card') {
        const n = ((d && d.number) || '').replace(/\D/g, '');
        if (n.length !== 16) throw err('invalid');
        if (n === '4000000000000002') throw err('declined');      // test card that always declines
        return { ref, method, last4: n.slice(-4) };
      }
      if (method === 'wallet') {
        if (wallet.get() + 1e-9 < order.total) throw err('insufficient');
        wallet.set(wallet.get() - order.total);
        return { ref, method };
      }
      return { ref, method };                                      // Apple Pay / Google Pay: always succeeds
    }
  };

  const Payments = {
    demo: true, provider: mock, wallet, tickets, qr,
    /* items: [{ds, network, lines[], from, to, n, unit, total, cur}] */
    order(items, cur) {
      return { id: 'ORD-' + rid(8), created: Date.now(), cur: cur || 'EUR', items, total: round2(items.reduce((a, i) => a + i.total, 0)) };
    },
    async pay(order, method, details) {
      const receipt = await this.provider.charge(order, method, details);
      const now = Date.now();
      const tk = order.items.map(i => {
        const id = 'TKT-' + rid(8);
        return { id, order: order.id, ds: i.ds, network: i.network, lines: i.lines, from: i.from, to: i.to, n: i.n,
                 price: i.total, cur: i.cur, bought: now, validUntil: now + VALID, code: ['DEMO', id, order.id, now].join('|') };
      });
      this.tickets.add(tk);
      return { order, receipt, tickets: tk };
    }
  };
  if (typeof module !== 'undefined') module.exports = Payments; else g.Payments = Payments;
})(typeof window !== 'undefined' ? window : globalThis);
