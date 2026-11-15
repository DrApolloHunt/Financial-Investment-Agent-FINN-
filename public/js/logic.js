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

// ---- formatting shared by screens and generated text ---------------------------------------
const nfIN = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** A target or reported figure, e.g. "₹27,000 cr", "8–10%", "more than 28%". */
export function target(t) {
  if (!t) return "";
  const u = t.unit || "";
  const f = (x) => (Math.abs(x) >= 1000 ? nfIN.format(x) : String(+x.toFixed(2)));
  const pre = u === "crore" ? "₹" : "";
  const post = u === "crore" ? " cr" : u === "%" ? "%" : u ? ` ${u}` : "";
  const lo = t.low, hi = t.high;
  if (lo == null && hi == null) return "";
  if (!plausible(lo, u) || !plausible(hi, u)) return "";   // a misread unit, not a number to show
  if (lo != null && hi != null && lo !== hi) return `${pre}${f(lo)}–${f(hi)}${post}`;
  return `${pre}${f(lo ?? hi)}${post}`;
}

/** No Indian company guides to ₹1 crore crore, or to a 10,000% anything. */
function plausible(x, unit) {
  if (x == null) return true;
  if (unit === "crore") return Math.abs(x) < 1e7;
  if (unit === "%") return Math.abs(x) <= 10000;
  return true;
}

// ---- "Before the call": questions to put to management, built from the ledger ---------------

const PRIORITY = { contradiction: 0, missed: 1, cut: 2, behind: 3, dropped: 4, due: 5 };

/** The call on which a promise was last spoken about. */
function lastMentioned(p) {
  const spoken = (p.history || []).filter((h) => h.kind && h.kind !== "not_mentioned");
  return spoken.length ? spoken[spoken.length - 1].quarter : p.made_in;
}

/** How many calls in a row, up to the latest, said nothing about it. */
function silentCalls(p) {
  let n = 0;
  for (const h of [...(p.history || [])].reverse()) {
    if (h.kind !== "not_mentioned") break;
    n += 1;
  }
  return n;
}

function reported(a) {
  const v = a && a.value != null ? target({ low: a.value, unit: a.unit }) : "";
  if (!v) return "";
  const period = String(a.period || "").replace(/\s*\((\d+) of (\d+) qtrs?\)/, ", $1 of $2 quarters");
  const src = String(a.source || "").replace(/^management, (.+) call$/, "management on the $1 call");
  if (src && period && src.includes(period)) return `${v}, per ${src}`;
  return [`${v}${period ? ` in ${period}` : ""}`, src && `per ${src}`].filter(Boolean).join(", ");
}

/**
 * Questions an investor could put to management on the next earnings call, most pressing
 * first, each with the promise it rests on and the evidence. Built in code from the ledger:
 * nothing here is the model's opinion.
 */
export function callQuestions(promises, latestQuarter, max = 6) {
  const fy = (latestQuarter || "").split(" ")[1] || "";
  const out = [];
  for (const p of promises || []) {
    const goal = target(p.target);
    const was = target(p.original_target);
    const got = reported(p.actual);
    const facts = [];
    let kind = null, ask = "";
    if (p.contradiction) {
      kind = "contradiction";
      ask = "You described this as delivered, but the reported numbers disagree. Which is right?";
      if (goal) facts.push(`Target: ${goal}`);
      if (got) facts.push(`Reported: ${got}`);
    } else if (p.status === "missed") {
      kind = "missed";
      ask = "This was missed. What went wrong, and what is the plan now?";
      if (goal) facts.push(`Target: ${goal}${p.horizon ? ` by ${p.horizon}` : ""}`);
      if (got) facts.push(`Reported: ${got}`);
    } else if (p.status === "slipping" && p.revised === "worse") {
      kind = "cut";
      const when = (p.history || []).find((h) => h.kind === "lowered" || h.kind === "delayed")?.quarter;
      ask = was && goal && was !== goal
        ? `Guidance went from ${was} to ${goal}${when ? ` on the ${when} call` : ""}. What changed, and is the new number safe?`
        : `Guidance was softened${when ? ` on the ${when} call` : ""}. What changed, and is the number still safe?`;
      if (got) facts.push(`Reported: ${got}`);
    } else if (p.status === "slipping") {
      kind = "behind";
      ask = "This is behind pace. What closes the gap?";
      if (goal) facts.push(`Target: ${goal}${p.horizon ? ` by ${p.horizon}` : ""}`);
      if (got) facts.push(`Reported: ${got}`);
    } else if (p.status === "dropped") {
      kind = "dropped";
      const n = silentCalls(p);
      ask = `You have not mentioned this for ${n > 1 ? `${n} calls` : "a call"}. Is it still the plan?`;
      facts.push(`Last mentioned on the ${lastMentioned(p)} call`);
    } else if ((p.status === "on_track" || p.status === "pending") && fy && (p.horizon_end || "").endsWith(fy)) {
      kind = "due";
      ask = `This is due by the end of ${fy}. Are you still on course?`;
      if (got) facts.push(`Reported: ${got}`);
    }
    if (!kind) continue;
    out.push({ id: p.id, kind, ask, statement: p.statement, made_in: p.made_in, facts,
               hard: p.specificity === "hard", source_url: p.source_url });
  }
  out.sort((a, b) => PRIORITY[a.kind] - PRIORITY[b.kind] || (b.hard - a.hard)
    || String(b.made_in || "").localeCompare(String(a.made_in || "")));
  // keep the list varied: at most three questions about promises that went quiet
  let quiet = 0;
  return out.filter((q) => q.kind !== "dropped" || ++quiet <= 3).slice(0, max);
}

/** The questions as plain text, ready to paste into notes before a call. */
export function questionsText(company, qs) {
  const lines = [`Questions for ${company} management, from FINN's promise ledger`, ""];
  qs.forEach((q, i) => {
    lines.push(`${i + 1}. ${q.ask}`);
    lines.push(`   Promise (${q.made_in} call): "${q.statement}"`);
    for (const f of q.facts) lines.push(`   ${f}`);
    lines.push("");
  });
  return lines.join("\n").trim();
}

// ---- "Brief me": a short spoken run-through of what matters --------------------------------

/** A company name as you would say it. */
export const spokenName = (n) => String(n || "")
  .replace(/\s*\((india|i)\)\s*/gi, " ")
  .replace(/\b(limited|ltd\.?)\s*$/i, "")
  .replace(/\s+India\s*$/i, "")
  .trim();

const crores = (v) => (v == null ? "" : `${Math.abs(v) >= 100 ? nfIN.format(Math.round(v)) : (+v.toFixed(1)).toString()} crore rupees`);
const change = (p) => (p == null ? "" : `${p >= 0 ? "up" : "down"} ${Math.abs(p) >= 10 ? Math.round(Math.abs(p)) : Math.abs(p).toFixed(1)} percent`);
const words = (s, max = 32) => {
  const w = String(s || "").replace(/\s+/g, " ").trim().split(" ");
  return w.length > max ? `${w.slice(0, max).join(" ")}…` : w.join(" ");
};
const sentence = (s) => (/[.!?…]$/.test(s) ? s : `${s}.`);

/** "Name: summary", unless the summary already opens with the company's name. */
const about = (name, text) => {
  const first = spokenName(name).split(" ")[0].toLowerCase();
  return first && String(text).toLowerCase().startsWith(first) ? text : `${spokenName(name)}: ${text}`;
};

const WINDOW_WORDS = { "24h": "in the last 24 hours", "3d": "in the last 3 days", "7d": "in the last 7 days",
  since: "since your last visit", custom: "in the dates you picked" };

/**
 * What FINN says, segment by segment. Each segment carries the key of the card it is about,
 * so the screen can follow along. `say` is plain words for a speech engine: no symbols.
 */
export function briefScript({ window: win, companies, promise = [], moves = [], material = [], buried = 0, max = 6 }) {
  const n = promise.length + moves.length + material.length;
  const segs = [];
  const when = WINDOW_WORDS[win] || "in this window";
  segs.push({ key: null, say: n === 0
    ? `Nothing needs you ${when}, across your ${companies} companies.`
    : `${n === 1 ? "One thing matters" : `${n} things matter`} ${when}, across your ${companies} companies.` });

  const items = [];
  for (const it of promise) {
    const c = it.card?.type === "results" ? it.card : null;
    if (c && c.ok) {
      const row = (k) => c.rows.find((r) => r.key === k);
      const rev = row("revenue"), pat = row("pat");
      let s = `${spokenName(it.name)} reported ${c.quarter || "quarterly"} results. `;
      if (rev) s += `Revenue ${crores(rev.value)}, ${change(rev.yoy?.pct) || "no comparison"} on last year. `;
      if (pat) s += `Profit after tax ${crores(pat.value)}, ${change(pat.yoy?.pct) || "no comparison"}. `;
      const pc = c.promise_check || [];
      if (pc.some((x) => x.verdict === "below")) s += "That falls short of what management promised.";
      else if (pc.length) s += "That is in line with what management promised.";
      items.push({ key: it.key, say: s.trim() });
    } else {
      const against = (it.promise_links || []).some((l) => l.effect === "undermines");
      items.push({ key: it.key, say: `${about(it.name, sentence(words(it.summary || it.headline)))}${against ? " It cuts against a promise." : ""}` });
    }
  }
  for (const m of moves) {
    const dir = m.chg >= 0 ? "rose" : "fell";
    const vol = m.vx >= 1.5 ? ` on ${m.vx.toFixed(1)} times its usual volume` : "";
    items.push({ key: m.key, say: m.filing
      ? `${spokenName(m.name)} ${dir} ${Math.abs(m.chg).toFixed(1)} percent${vol}, after a filing: ${sentence(words(m.filing, 20))}`
      : `${spokenName(m.name)} ${dir} ${Math.abs(m.chg).toFixed(1)} percent${vol}, and no filing explains it.` });
  }
  for (const it of material) {
    if (it.card?.type === "people") {
      const verb = { appointed: "is appointed", resigned: "has resigned", retired: "is retiring", redesignated: "takes a new role", ceased: "has left" };
      const ch = (it.card.changes || []).slice(0, 2).map((c) => `${c.name} ${verb[c.action] || "changes role"}${c.role ? ` as ${c.role}` : ""}`);
      items.push({ key: it.key, say: `${spokenName(it.name)}: a management change. ${ch.map(sentence).join(" ")}` });
    } else {
      items.push({ key: it.key, say: about(it.name, sentence(words(it.summary || it.headline))) });
    }
  }
  segs.push(...items.slice(0, max));
  if (items.length > max) segs.push({ key: null, say: `And ${items.length - max} more on screen.` });
  if (buried) segs.push({ key: null, say: `${buried === 1 ? "One routine filing was" : `${buried} routine filings were`} buried.` });
  return segs;
}
