// Rendering helpers. Every interpolated value is escaped unless wrapped in raw().

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
export const raw = (s) => ({ __raw: String(s) });

function render(v) {
  if (v == null || v === false) return "";
  if (Array.isArray(v)) return v.map(render).join("");
  if (typeof v === "object" && "__raw" in v) return v.__raw;
  return esc(v);
}

export function html(strings, ...vals) {
  let out = "";
  strings.forEach((s, i) => { out += s; if (i < vals.length) out += render(vals[i]); });
  return raw(out);
}

export const mount = (el, tpl) => { el.innerHTML = tpl.__raw; };

// ---- numbers ----------------------------------------------------------------
const nf0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const crore = (v) => (v == null ? "—" : `₹${nf0.format(v)} cr`);
export const rupees = (v) => (v == null ? "—" : `₹${nf2.format(v)}`);
const nfd = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
export const num = (v) => (v == null ? "—" : Math.abs(v) < 100 ? nfd.format(v) : nf0.format(v));
/** Only http(s) links leave the app. */
export const link = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "#");
export const pct = (v, digits = 1) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}%`);
export const sign = (v) => (v == null ? "flat" : v > 0.05 ? "pos" : v < -0.05 ? "neg" : "flat");

export function target(t) {
  if (!t) return "";
  const u = t.unit || "";
  const f = (x) => (Math.abs(x) >= 1000 ? nf0.format(x) : String(+x.toFixed(2)));
  const pre = u === "crore" ? "₹" : "";
  const post = u === "crore" ? " cr" : u === "%" ? "%" : u ? ` ${u}` : "";
  const lo = t.low, hi = t.high;
  if (lo == null && hi == null) return "";
  if (lo != null && hi != null && lo !== hi) return `${pre}${f(lo)}–${f(hi)}${post}`;
  return `${pre}${f(lo ?? hi)}${post}`;
}

// ---- time ---------------------------------------------------------------------
// In demo-snapshot mode the app's "now" is the moment the snapshot was taken.
let CLOCK = null;
export const setNow = (ms) => { CLOCK = ms; };
export const nowMs = () => CLOCK ?? Date.now();
const tf = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
const df = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
const longDate = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" });
const stamp = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
export const stampOf = (iso) => stamp.format(new Date(iso));
export const today = () => longDate.format(new Date(nowMs()));
export function when(iso) {
  if (!iso) return "";
  const d = new Date(iso), now = new Date(nowMs());
  const days = Math.floor((now - d) / 864e5);
  const sameDay = df.format(d) === df.format(now);
  if (sameDay) return tf.format(d).replace(" ", "").toLowerCase();
  if (days < 1) return `yesterday ${tf.format(d).replace(" ", "").toLowerCase()}`;
  return df.format(d);
}
export const day = (isoDate) => df.format(new Date(isoDate + "T12:00:00+05:30"));
export function ago(iso) {
  const m = Math.round((nowMs() - new Date(iso)) / 6e4);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// ---- status marks ----------------------------------------------------------------
export const STATUS = {
  missed:   { label: "Missed",      color: "var(--miss)" },
  slipping: { label: "Slipping",    color: "var(--slip)" },
  dropped:  { label: "Dropped",     color: "var(--drop)" },
  on_track: { label: "On track",    color: "var(--track)" },
  pending:  { label: "Not yet due", color: "var(--ink-3)" },
  kept:     { label: "Kept",        color: "var(--kept)" },
};
export const STATUS_ORDER = ["missed", "slipping", "dropped", "on_track", "pending", "kept"];

export function mark(status, title) {
  const c = (STATUS[status] || STATUS.pending).color;
  const t = esc(title || (STATUS[status] || STATUS.pending).label);
  const shapes = {
    kept: `<circle cx="8" cy="8" r="5.5" fill="${c}"/>`,
    on_track: `<circle cx="8" cy="8" r="5.5" fill="none" stroke="${c}" stroke-width="1.6"/><circle cx="8" cy="8" r="2.4" fill="${c}"/>`,
    pending: `<circle cx="8" cy="8" r="5.5" fill="none" stroke="${c}" stroke-width="1.6"/>`,
    slipping: `<circle cx="8" cy="8" r="5.5" fill="none" stroke="${c}" stroke-width="1.6"/><path d="M2.5 8a5.5 5.5 0 0 0 11 0z" fill="${c}"/>`,
    missed: `<path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="${c}" stroke-width="2.2" stroke-linecap="round"/>`,
    dropped: `<circle cx="8" cy="8" r="5.5" fill="none" stroke="${c}" stroke-width="1.4" stroke-dasharray="2.2 1.8"/><path d="M2 14L14 2" stroke="${c}" stroke-width="1.6" stroke-linecap="round"/>`,
  };
  return raw(`<svg class="mk" viewBox="0 0 16 16" role="img" aria-label="${t}"><title>${t}</title>${shapes[status] || shapes.pending}</svg>`);
}

/** A plain ledger entry: a filing that is not about a promise. */
export const entry = (title = "Filing") =>
  raw(`<svg class="mk" viewBox="0 0 16 16" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title><path d="M3.5 8h9" stroke="var(--ink-3)" stroke-width="2" stroke-linecap="round"/></svg>`);

export function strip(promises) {
  const ps = [...promises].sort((a, b) => (a.made_in || "").localeCompare(b.made_in || ""));
  return html`<span class="strip">${ps.map((p) => mark(p.status, `${STATUS[p.status]?.label}: ${p.statement}`))}</span>`;
}

export function countsLine(counts) {
  const parts = STATUS_ORDER.filter((s) => counts?.[s]).map((s) => `${counts[s]} ${STATUS[s].label.toLowerCase()}`);
  return parts.join(", ");
}

// ---- tiny charts (single series each; no dual axes) ----------------------------------
export function sparkline(values, { w = 320, h = 44 } = {}) {
  const v = values.filter((x) => x != null);
  if (v.length < 2) return raw("");
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const pts = v.map((y, i) => `${((i / (v.length - 1)) * w).toFixed(1)},${(h - 3 - ((y - lo) / span) * (h - 6)).toFixed(1)}`);
  const up = v[v.length - 1] >= v[0];
  return raw(`<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Price over the period, ${up ? "up" : "down"} ${Math.abs((v[v.length - 1] / v[0] - 1) * 100).toFixed(1)}%">
    <polyline points="${pts.join(" ")}" fill="none" stroke="var(--ink-2)" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`);
}

export function barChart(id, labels, values, fmt) {
  const w = 320, h = 92, pad = 16;
  const n = values.length, max = Math.max(...values.filter((x) => x != null), 1);
  const bw = (w / n) * 0.62, step = w / n;
  const bars = values.map((v, i) => {
    if (v == null) return "";
    const bh = Math.max(2, (v / max) * (h - pad - 4));
    const x = i * step + (step - bw) / 2, y = h - pad - bh;
    return `<rect class="bar${i === n - 1 ? " on" : ""}" data-i="${i}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="2"/>
            <rect class="hit" data-i="${i}" x="${(i * step).toFixed(1)}" y="0" width="${step.toFixed(1)}" height="${h}"/>`;
  }).join("");
  const ticks = labels.map((l, i) => ((n - 1 - i) % 4 === 0 ? `<text class="ax" x="${(i * step + step / 2).toFixed(1)}" y="${h - 3}" text-anchor="middle">${esc(l)}</text>` : "")).join("");
  return raw(`<svg id="${id}" viewBox="0 0 ${w} ${h}" role="img" aria-label="Bar chart">
    <line class="gl" x1="0" x2="${w}" y1="${h - pad}" y2="${h - pad}"/>${bars}${ticks}</svg>`);
}

export function lineChart(id, labels, values, { unit = "%" } = {}) {
  const w = 320, h = 92, pad = 16;
  const v = values.map((x) => (x == null ? null : x));
  const ok = v.filter((x) => x != null);
  if (ok.length < 2) return raw("");
  const lo = Math.min(...ok), hi = Math.max(...ok);
  const span = hi - lo || 1, n = v.length, step = w / n;
  const y = (x) => h - pad - 6 - ((x - lo) / span) * (h - pad - 18);
  const pts = v.map((x, i) => (x == null ? null : [i * step + step / 2, y(x)])).filter(Boolean);
  const last = pts[pts.length - 1];
  const hits = v.map((x, i) => `<rect class="hit" data-i="${i}" x="${(i * step).toFixed(1)}" y="0" width="${step.toFixed(1)}" height="${h}"/>`).join("");
  return raw(`<svg id="${id}" viewBox="0 0 ${w} ${h}" role="img" aria-label="Line chart">
    <line class="gl" x1="0" x2="${w}" y1="${h - pad}" y2="${h - pad}"/>
    <text class="ax" x="0" y="${(y(hi) - 4).toFixed(1)}">${hi.toFixed(unit ? 1 : 0)}${unit}</text>
    ${hi - lo >= 0.1 ? `<text class="ax" x="0" y="${(y(lo) + 12).toFixed(1)}">${lo.toFixed(unit ? 1 : 0)}${unit}</text>` : ""}
    <polyline class="ln" points="${pts.map((p) => p.map((c) => c.toFixed(1)).join(",")).join(" ")}"/>
    <circle class="dot" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="4"/>${hits}</svg>`);
}

export function wireChart(root, id, labels, values, fmt) {
  const svg = root.querySelector(`#${id}`);
  const out = svg?.parentElement.querySelector(".read");
  if (!svg || !out) return;
  const show = (i) => {
    out.textContent = `${labels[i]}: ${values[i] == null ? "—" : fmt(values[i])}`;
    svg.querySelectorAll(".bar").forEach((b) => b.classList.toggle("on", +b.dataset.i === i));
  };
  svg.querySelectorAll(".hit").forEach((r) => {
    const i = +r.dataset.i;
    r.addEventListener("mouseenter", () => show(i));
    r.addEventListener("click", () => show(i));
  });
  show(values.length - 1);
}

// ---- app-style building blocks ---------------------------------------------------------
/** A company thumbnail: initials on a tint picked from the symbol, so it stays the same everywhere. */
export function avatar(symbol, name, cls = "") {
  const s = String(symbol || "?");
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360;
  const words = String(name || s).replace(/\b(Ltd|Limited|India|Industries|Company|Corporation|The)\b\.?/gi, "").trim().split(/\s+/).filter(Boolean);
  const ini = (words.length > 1 ? words[0][0] + words[1][0] : s.slice(0, 2)).toUpperCase();
  return raw(`<span class="av ${cls}" style="--h:${h}" aria-hidden="true">${esc(ini)}</span>`);
}

/** A status as a tag: its mark and its word, on a tint of its colour. */
export function tag(status, text) {
  const st = STATUS[status] || STATUS.pending;
  return raw(`<span class="tag" style="--c:${st.color}">${mark(status).__raw}${esc(text || st.label)}</span>`);
}

/** A price move as a filled badge, like a rating badge. */
export function moveBadge(chg) {
  if (chg == null) return raw("");
  const cls = chg > 0.05 ? "up" : chg < -0.05 ? "down" : "flat";
  const arrow = cls === "up" ? "▲" : cls === "down" ? "▼" : "";
  return raw(`<span class="badge ${cls}">${arrow} ${Math.abs(chg).toFixed(1)}%</span>`);
}

const ICONS = {
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L20 20"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  doc: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>',
  book: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
  flag: '<path d="M6 21V4M6 4h11l-2 4 2 4H6"/>',
  pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20h4"/>',
  box: '<path d="M4 8h16v12H4zM3 4h18v4H3zM10 12h4"/>',
  chev: '<path d="M6 9l6 6 6-6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  spark: '<path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z"/>',
  up: '<path d="M6 15l6-6 6 6"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
};
export const icon = (name, cls = "") => raw(`<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`);

/** FINN's mark: a ledger page with a tick, on the brand colour. */
export const logo = () => raw(`<svg viewBox="0 0 34 34" aria-hidden="true"><rect width="34" height="34" rx="10" fill="var(--brand)"/>
  <path d="M10 9h11l3 3v13H10z" fill="none" stroke="var(--on-brand)" stroke-width="2" stroke-linejoin="round"/>
  <path d="M13.5 18l2.5 2.5 4.5-5" fill="none" stroke="var(--on-brand)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`);
