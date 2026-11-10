import * as data from "../data.js";
import { LABELS } from "../categories.js";
import { tier } from "../logic.js";
import {
  barChart, countsLine, crore, day, entry, html, lineChart, mark, mount, num, pct, rupees, sign, sparkline,
  link, STATUS, STATUS_ORDER, strip, target, when, wireChart,
} from "../ui.js";

export async function companyView(el, ctx, sym, alive) {
  const [co, feed] = await Promise.all([data.company(sym), data.feed().catch(() => ({ items: [] }))]);
  if (!alive()) return;
  if (!co) {
    location.hash = `#/research/${sym}`;
    return;
  }
  renderCompany(el, co, feed.items.filter((it) => it.symbol === sym), ctx, { back: "#/ledgers" });
}

const KIND = {
  reiterated: "Reiterated", raised: "Raised the target", lowered: "Lowered the target", delivered: "Said delivered",
  missed: "Said missed", delayed: "Pushed out", withdrawn: "Withdrew it", not_mentioned: "Not mentioned",
};

function history(p) {
  const evs = p.history || [];
  return html`<ol class="timeline">
    <li><span class="q">${p.made_in}</span><span><span class="k">Promised</span>${p.speaker ? html`, ${p.speaker}` : ""}</span></li>
    ${evs.map((e) => html`<li><span class="q">${e.quarter}</span><span class="${e.kind === "not_mentioned" ? "silent" : ""}">
      <span class="k">${KIND[e.kind] || e.kind}</span>${e.target && (e.target.low != null || e.target.high != null) ? html`: now ${target({ ...e.target, unit: p.target?.unit })}` : ""}${e.reported != null ? html`, reported ${num(e.reported)}${p.target?.unit === "%" ? "%" : ""}` : ""}
      ${e.quote ? html`<br><span class="qt">“${e.quote}”</span>` : ""}</span></li>`)}
    ${(p.evidence || []).map((e) => html`<li><span class="q">${when(e.ts)}</span><span><span class="k">Filing</span>: ${e.headline}
      ${e.note ? html`<br><span class="silent">${e.note}</span>` : ""}
      ${e.attachment ? html`<br><a href="${link(e.attachment)}" target="_blank" rel="noopener">Open filing</a>` : ""}</span></li>`)}
  </ol>`;
}

function promiseRow(p) {
  const t = target(p.target);
  const alarm = p.contradiction;
  return html`<div class="row tap" data-p="${p.id}">
    <div class="m">${mark(p.status)}</div>
    <div class="b" role="button" tabindex="0" aria-expanded="false">
      <div class="p-stmt" style="font-family:var(--serif);font-weight:500">${p.statement}</div>
      <div class="p-meta">${STATUS[p.status]?.label}${t ? `, target ${t}` : ""}${p.horizon ? `, by ${p.horizon}` : ""}${p.revised === "worse" ? ", target cut" : p.revised === "better" ? ", target raised" : ""}</div>
      <div class="p-why ${alarm ? "alarm" : ""}">${p.reason}</div>
      <div class="p-more">
        ${p.quote ? html`<blockquote class="quote">“${p.quote}”<cite>${p.speaker || "Management"}, ${p.made_in} earnings call${p.source_url ? html`, <a href="${link(p.source_url)}" target="_blank" rel="noopener">transcript</a>` : ""}</cite></blockquote>` : ""}
        ${history(p)}
        ${p.actual ? html`<p class="actual">Delivered: <b>${num(p.actual.value)}${p.actual.unit === "%" ? "%" : p.actual.unit ? ` ${p.actual.unit}` : ""}</b> for ${p.actual.period}. <span class="foot">Source: ${p.actual.source}.</span></p>` : ""}
        ${p.verdict && !p.verdict.startsWith(p.statement) && p.verdict !== p.reason ? html`<p class="actual">${p.verdict}</p>` : ""}
      </div>
    </div></div>`;
}

export function renderCompany(el, co, filings, ctx, { back, banner } = {}) {
  const L = co.ledger || { promises: [], counts: {} };
  const px = co.prices || [];
  const last = px[px.length - 1], prev = px[px.length - 2];
  const chg = last && prev ? (last.c / prev.c - 1) * 100 : null;
  const groups = STATUS_ORDER.map((s) => [s, L.promises.filter((p) => p.status === s)]).filter(([, ps]) => ps.length);
  const q = co.quarters || { periods: [], rows: {} };
  const periods = q.periods.slice(-12);
  const rev = (q.rows.revenue || []).slice(-12);
  // margin from the rupee rows (screener's % row is rounded to whole numbers)
  const eb = (q.rows.ebitda || []).slice(-12);
  const margin = rev.map((r, i) => (r && eb[i] != null ? +((eb[i] / r) * 100).toFixed(1) : null));
  const s = ctx.settings;
  const recent = filings.map((it) => ({ ...it, tier: tier(it, s.care) })).filter((it) => it.tier !== "routine").slice(0, 6);

  mount(el, html`
    ${back ? html`<a class="back" href="${back}">Back</a>` : ""}
    ${banner || ""}
    <div class="cohead">
      <div><h1 class="title">${co.name}</h1><div class="meta">${co.symbol}${co.sector ? `, ${co.sector}` : ""}${co.basis ? `, ${co.basis} figures` : ""}</div></div>
      <div class="price">${last ? html`<b>${rupees(last.c)}</b><br><span class="${sign(chg)}">${pct(chg)}</span>` : ""}</div>
    </div>
    ${px.length > 2 ? html`${sparkline(px.map((p) => p.c))}<p class="foot">Closing prices, six months to ${day(last.d)}</p>` : ""}

    ${L.credibility ? html`<p class="cred">${L.credibility}<span class="by">FINN's read of ${L.calls?.length || "the last"} earnings calls against reported numbers.</span></p>` : ""}

    <section class="section">
      <h2>Promises <span class="n">${L.promises.length}</span></h2>
      ${L.promises.length ? html`<p class="lede" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${strip(L.promises)}<span>${countsLine(L.counts)}</span></p>` : ""}
      ${L.promises.length ? html`<div class="ledger">${groups.map(([st, ps]) => html`
          <div class="group-h">${mark(st)}${STATUS[st].label} (${ps.length})</div>
          ${ps.map(promiseRow)}`)}</div>`
        : html`<p class="note">${co.transcripts?.length ? "No forward-looking commitments were found in the calls read." : "No earnings-call transcripts are available for this company, so there is nothing to hold management to yet."}</p>`}
    </section>

    ${rev.length ? html`<section class="section">
      <h2>Delivered, quarter by quarter</h2>
      <div class="charts">
        <div class="chart"><h3>Revenue, ₹ crore</h3>${barChart("c-rev", periods, rev)}<div class="read"></div></div>
        ${margin.some((m) => m != null) ? html`<div class="chart"><h3>${co.is_lender ? "Financing margin" : "EBITDA margin"}, %</h3>${lineChart("c-mar", periods, margin)}<div class="read"></div></div>` : ""}
      </div>
      <p class="foot">Exchange-reported quarterly figures. Tap a quarter to read its value.</p>
    </section>` : ""}

    ${recent.length ? html`<section class="section"><h2>Recent filings that matter</h2>
      <div class="ledger">${recent.map((it) => html`<div class="row"><div class="m">${entry(LABELS[it.category] || "Filing")}</div><div class="b">
        <div class="who"><b>${LABELS[it.category] || it.category}</b><span class="t">${when(it.ts)}</span></div>
        <p class="what">${it.summary || it.headline}</p>
        ${it.attachment ? html`<div class="links"><a href="${link(it.attachment)}" target="_blank" rel="noopener">Open filing</a></div>` : ""}</div></div>`)}</div>
    </section>` : ""}

    <section class="section"><h2>Sources</h2>
      <p class="src">Promises come only from the company's own earnings-call transcripts${L.calls?.length ? ":" : "."}
        ${(L.calls || []).map((c, i) => html`${i ? ", " : " "}<a href="${link(c.url)}" target="_blank" rel="noopener">${c.quarter}</a>`)}.
        Delivered numbers come from exchange-reported results${co.url ? html` via <a href="${link(co.url)}" target="_blank" rel="noopener">screener.in</a>` : ""}.
        No news, broker notes or model memory are used.${L.verdict_model ? ` Verdicts written by ${L.verdict_model}.` : ""}</p>
    </section>
  `);

  el.querySelectorAll(".row.tap > .b").forEach((b) => {
    const toggle = () => {
      const row = b.parentElement, open = !row.classList.contains("open");
      row.classList.toggle("open", open);
      b.setAttribute("aria-expanded", String(open));
    };
    b.addEventListener("click", (e) => { if (!e.target.closest("a")) toggle(); });
    b.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
  });
  if (rev.length) wireChart(el, "c-rev", periods, rev, (v) => crore(v));
  if (margin.some((m) => m != null)) wireChart(el, "c-mar", periods, margin, (v) => `${v.toFixed(1)}%`);
}
