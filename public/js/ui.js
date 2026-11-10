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

export function lineChart(id, labels, values) {
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
    <text class="ax" x="0" y="${(y(hi) - 4).toFixed(1)}">${hi.toFixed(1)}%</text>
    ${hi - lo >= 0.1 ? `<text class="ax" x="0" y="${(y(lo) + 12).toFixed(1)}">${lo.toFixed(1)}%</text>` : ""}
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
