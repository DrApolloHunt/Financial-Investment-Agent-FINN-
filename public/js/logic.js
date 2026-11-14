// Pure decision logic for the digest. Mirrors finn/triage.py and finn/moves.py so
// that the investor's own settings re-rank everything instantly in the browser.

export const ROUTINE_SUBTYPES = {
  results: ["intimation", "ad", "trading_window", "deck", "companion"],
  management_change: ["board", "other"],
  credit_rating: ["reaffirmed"],
  press_release: ["clarification_routine"],
};

export function isRoutine(it) {
  return it.routine || (ROUTINE_SUBTYPES[it.category] || []).includes(it.subtype);
}

/** "promise" | "material" | "routine" */
export function tier(it, care) {
  if ((it.promise_links && it.promise_links.length) || (it.category === "results" && it.subtype === "financials")) return "promise";
  if (isRoutine(it) || !care[it.category]) return "routine";
  if (it.importance === "low") return "routine";
  return "material";
}

export function windowStart(mode, now, session) {
  const h = { "24h": 24, "3d": 72, "7d": 168 }[mode];
  if (h) return new Date(now - h * 3600e3);
  if (mode === "since" && session?.start) {
    const s = new Date(session.start);
    if (now - s < 7 * 864e5) return s;
  }
  return new Date(now - 24 * 3600e3);
}

const IST = 5.5 * 3600e3;
/** Calendar date (YYYY-MM-DD) in India for a timestamp. */
export const istDate = (ms) => new Date(ms + IST).toISOString().slice(0, 10);

/**
 * The window as { start, end }. Custom ranges are whole days in India time, from the
 * start of `from` to the end of `to`; reversed dates are swapped and the end never
 * runs past `now`. Missing dates default to the last seven days.
 */
export function windowRange(mode, now, session, range = {}) {
  if (mode !== "custom") return { start: windowStart(mode, now, session), end: new Date(now) };
  let from = range.from || istDate(now - 6 * 864e5), to = range.to || istDate(now);
  if (from > to) [from, to] = [to, from];
  const start = new Date(`${from}T00:00:00+05:30`);
  const end = new Date(Math.min(now, new Date(`${to}T23:59:59.999+05:30`).getTime()));
  return { start, end, from, to };
}

/** Unusual end-of-day moves by the investor's thresholds. */
export function unusual(prices, { movePct, volX, lookback = 20 }) {
  const out = [];
  for (let i = 1; i < prices.length; i++) {
    const prev = prices[i - 1], cur = prices[i];
    if (!prev.c) continue;
    const chg = (cur.c / prev.c - 1) * 100;
    const win = prices.slice(Math.max(0, i - lookback), i).map((p) => p.v).filter(Boolean);
    const avg = win.length ? win.reduce((a, b) => a + b, 0) / win.length : 0;
    const vx = avg ? cur.v / avg : 0;
    if (Math.abs(chg) >= movePct || vx >= volX) {
      out.push({ d: cur.d, prev_d: prev.d, chg: +chg.toFixed(2), vx: +vx.toFixed(2),
                 priceHit: Math.abs(chg) >= movePct, volHit: vx >= volX });
    }
  }
  return out;
}

const close = (isoDate) => new Date(`${isoDate}T15:30:00+05:30`);

/** Filings disseminated after the previous close and up to this close. */
export function explaining(move, filings) {
  const a = close(move.prev_d), b = close(move.d);
  return filings.filter((f) => {
    if (!f.ts || f.category === "unclassified" || isRoutine(f)) return false;
    const t = new Date(f.ts);
    return t > a && t <= b;
  });
}

/** Fold companion filings into the results they belong to, and pair CFO in/out. */
export function group(items) {
  const out = [], used = new Set();
  const byTime = [...items].sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
  const near = (a, b) => Math.abs(new Date(a.ts) - new Date(b.ts)) < 24 * 3600e3;
  for (const it of byTime) {          // pass 1: results claim their companions
    if (it.category === "results" && it.subtype === "financials") {
      it.related = byTime.filter((o) => o !== it && o.symbol === it.symbol && o.category === "results"
        && ["companion", "deck", "ad"].includes(o.subtype) && near(o, it));
      it.related.forEach((o) => used.add(o.id));
    }
  }
  for (const it of byTime) {          // pass 2: emit, pairing management in/out
    if (used.has(it.id)) continue;
    if (it.category === "management_change" && it.card?.type === "people") {
      const twins = byTime.filter((o) => o !== it && o.symbol === it.symbol && o.category === "management_change"
        && o.card?.type === "people" && near(o, it) && !used.has(o.id));
      twins.forEach((o) => used.add(o.id));
      if (twins.length) it.twins = twins;
    }
    used.add(it.id);
    out.push(it);
  }
  return out;
}

/** "9 routine paperwork, 4 investor meetings, …" for the buried drawer. */
const lc = (s) => (/^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);
const plural = (k, n) => (n > 1 && !/(paperwork|notices|s)$/.test(k) ? `${k}s` : k);

export function buriedKinds(items, labels) {
  const c = {};
  for (const it of items) {
    const k = it.category === "results" ? `results ${it.subtype === "intimation" ? "notices" : "paperwork"}` : lc(labels[it.category] || it.category);
    c[k] = (c[k] || 0) + 1;
  }
  return Object.entries(c).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${n} ${plural(k, n)}`);
}
