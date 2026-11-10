// Data access: static JSON written by the pipeline, plus the on-demand research API.

const params = new URLSearchParams(location.search);
export const FIXTURES = params.has("fixtures");
const BASE = FIXTURES ? "/dev-fixtures/" : "/data/";

const memo = new Map();
export const reset = () => memo.clear();

async function getJSON(url, { fresh = false } = {}) {
  if (!fresh && memo.has(url)) return memo.get(url);
  const p = fetch(url, { cache: "no-cache" }).then(async (r) => {
    if (!r.ok) { const e = new Error(`${r.status} ${url}`); e.status = r.status; throw e; }
    return r.json();
  });
  memo.set(url, p);
  p.catch(() => memo.delete(url));
  return p;
}

export const meta = () => getJSON(BASE + "meta.json");
export const portfolio = () => getJSON(BASE + "portfolio.json");
export const feed = () => getJSON(BASE + "feed.json");

export async function company(sym) {
  try {
    return await getJSON(`${BASE}companies/${encodeURIComponent(sym)}.json`);
  } catch (e) {
    if (e.status === 404) return null;
    throw e;
  }
}

// ---- settings & session (per viewer, best effort) ------------------------------
const KEY = "finn:settings:v1";
export const DEFAULTS = { movePct: 4, volX: 2, window: "24h", care: null };

export function loadSettings() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; }
  catch { return { ...DEFAULTS }; }
}
export function saveSettings(s) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ }
}

/** "Since you last looked": the start only moves forward after 30 minutes away. */
export function session() {
  const k = "finn:session:v1", now = Date.now();
  let s = {};
  try { s = JSON.parse(localStorage.getItem(k) || "{}"); } catch { /* ignore */ }
  if (!s.last || now - s.last > 30 * 60e3) s.start = s.last || null;
  s.last = now;
  try { localStorage.setItem(k, JSON.stringify(s)); } catch { /* ignore */ }
  return s;
}

// ---- research API ---------------------------------------------------------------------
async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  let j = {};
  try { j = await r.json(); } catch { /* non-JSON error page */ }
  if (!r.ok) throw new Error(j.error || `The research service answered ${r.status}.`);
  return j;
}

export function cachedResearch(sym) {
  try {
    const v = JSON.parse(localStorage.getItem(`finn:r:${sym}`) || "null");
    if (v && Date.now() - v.at < 7 * 864e5) return v.co;
  } catch { /* ignore */ }
  return null;
}

function keepResearch(sym, co) {
  try { localStorage.setItem(`finn:r:${sym}`, JSON.stringify({ at: Date.now(), co })); } catch { /* quota */ }
}

/** Build a ledger for any NSE symbol, reporting progress as each call is read. */
export async function research(sym, onEvent) {
  const pre = await company(sym);
  if (pre?.ledger?.promises) { onEvent({ type: "prebuilt", co: pre }); return pre; }
  const co = await api(`/api/company?t=${encodeURIComponent(sym)}`);
  onEvent({ type: "company", co });
  if (!co.transcripts?.length) {
    const out = { ...co, ledger: null };
    onEvent({ type: "nocalls" });
    return out;
  }
  let state = null;
  for (const t of [...co.transcripts].reverse()) {
    onEvent({ type: "reading", t });
    try {
      const r = await api("/api/ledger_step", { state, symbol: co.symbol, name: co.name, quarter: t.quarter, url: t.url });
      state = r.state;
      onEvent({ type: "read", t, found: r.found, updated: r.updated });
    } catch (e) {
      onEvent({ type: "readfail", t, error: e.message });
    }
  }
  if (!state) throw new Error("No earnings call could be read, so there is no ledger to build.");
  onEvent({ type: "judging" });
  const ledger = await api("/api/ledger_finalize", { state, quarters: co.quarters, latest: co.latest_quarter });
  const out = { ...co, ledger };
  keepResearch(sym, out);
  return out;
}
