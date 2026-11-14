import * as data from "../data.js";
import { LABELS } from "../categories.js";
import { buriedKinds, explaining, group, istDate, tier, unusual, windowRange } from "../logic.js";
import { ago, entry, html, mark, mount, nowMs, num, pct, raw, sign, stampOf, target, today, when, link } from "../ui.js";

const WINDOWS = [["24h", "24 hours"], ["3d", "3 days"], ["7d", "7 days"], ["since", "Since last visit"], ["custom", "Dates"]];

export async function todayView(el, ctx, _a, alive) {
  const [meta, port, feed] = await Promise.all([
    data.meta().catch(() => null), data.portfolio().catch(() => null), data.feed().catch(() => null)]);
  if (!alive()) return;
  if (!feed || !port) {
    return mount(el, html`<header class="head"><p class="date">${today()}</p></header>
      <div class="empty"><b>No filings collected yet.</b>FINN fills this page from exchange filings and prices. The data refresh runs every hour during market hours and after the close.</div>`);
  }
  const s = ctx.settings;
  const now = nowMs();
  const { start, end, from, to } = windowRange(s.window, now, ctx.session, s.range || {});
  const names = Object.fromEntries(port.companies.map((c) => [c.symbol, c.name]));

  const all = feed.items.map((it) => ({ ...it, tier: tier(it, s.care) }));
  const inWin = all.filter((it) => it.ts && new Date(it.ts) >= start && new Date(it.ts) <= end);
  const earliest = all.reduce((m, it) => (it.ts && it.ts < m ? it.ts : m), new Date(now).toISOString());
  const grouped = group(inWin);

  // price moves, judged by the investor's own thresholds, paired with filings
  const unexplained = [], movedWith = [];
  for (const c of port.companies) {
    for (const m of unusual(c.recent || [], { movePct: s.movePct, volX: s.volX })) {
      const close = new Date(`${m.d}T15:30:00+05:30`);
      if (close < start || close > end) continue;
      const why = explaining(m, all.filter((f) => f.symbol === c.symbol));
      const host = why.map((f) => grouped.find((g) => g.id === f.id)).find(Boolean);
      if (host) host.move = m;
      else if (why.length) movedWith.push({ c, m, f: why[0] });
      else unexplained.push({ c, m });
    }
  }

  const promise = grouped.filter((it) => it.tier === "promise");
  const material = grouped.filter((it) => it.tier === "material");
  const buried = grouped.filter((it) => it.tier === "routine");
  const n = promise.length + material.length + unexplained.length + movedWith.length;

  const hero = n === 0 ? "Nothing needs you." : n === 1 ? "1 thing matters." : `${n} things matter.`;
  const stale = !ctx.snapshot && meta?.generated_at && now - new Date(meta.generated_at) > 30 * 3600e3;

  mount(el, html`
    <header class="head">
      <p class="date">${today()}</p>
      <h1 class="hero">${hero} <span class="quiet">${buried.length} buried.</span></h1>
      <div class="seg" role="group" aria-label="Time window">
        ${WINDOWS.map(([k, label]) => html`<button type="button" data-win="${k}" aria-pressed="${s.window === k}">${label}</button>`)}
      </div>
      ${s.window === "custom" ? html`<div class="range">
        <label>From <input type="date" data-range="from" value="${from}" min="${istDate(Date.parse(earliest))}" max="${istDate(now)}"></label>
        <label>to <input type="date" data-range="to" value="${to}" min="${istDate(Date.parse(earliest))}" max="${istDate(now)}"></label>
        <span class="foot">Filings collected from ${when(earliest)}.</span></div>` : ""}
      <p class="sub">${s.window === "since" && !ctx.session.start ? "First visit: showing the last 24 hours. " : ""}${meta?.generated_at && !ctx.snapshot ? `Data updated ${ago(meta.generated_at)}.` : ""}</p>
      ${ctx.snapshot ? html`<p class="banner">Demo snapshot taken ${stampOf(meta.generated_at)}. Filings and prices are frozen at that moment, so "the last 24 hours" means the 24 hours before it. The Research tab works live on any company.</p>` : ""}
      ${data.FIXTURES ? html`<p class="banner">Sample data: these companies, filings and quotes are fictional.</p>` : ""}
      ${stale ? html`<p class="banner">The last data refresh was ${ago(meta.generated_at)}. Filings since then are not shown.</p>` : ""}
    </header>

    ${promise.length ? html`<section class="section">
      <h2>Moves a promise <span class="n">${promise.length}</span></h2>
      <p class="lede">Results, and filings that bear on something management promised.</p>
      <div class="ledger">${promise.map((it) => promiseRow(it, names))}</div></section>` : ""}

    ${unexplained.length || movedWith.length ? html`<section class="section">
      <h2>Price moved <span class="n">${unexplained.length + movedWith.length}</span></h2>
      <p class="lede">Beyond ${s.movePct}% in a day or ${s.volX}× the usual volume, by your settings.</p>
      <div class="ledger">
        ${unexplained.map(({ c, m }) => html`<div class="row"><div class="m">${moveGlyph(m)}</div><div class="b">
          <div class="who"><b>${c.symbol}</b> ${c.name}<span class="t">${dayLabel(m.d)}</span></div>
          <p class="what">${moveText(m)}</p>
          <p class="why">No filing since the previous close explains it.</p>
          <div class="links"><a href="#/c/${c.symbol}">Open ledger</a></div></div></div>`)}
        ${movedWith.map(({ c, m, f }) => html`<div class="row"><div class="m">${moveGlyph(m)}</div><div class="b">
          <div class="who"><b>${c.symbol}</b> ${c.name}<span class="t">${dayLabel(m.d)}</span></div>
          <p class="what">${moveText(m)}</p>
          <p class="why">Filed before this window: ${f.summary || f.headline}</p>
          <div class="links">${f.attachment ? html`<a href="${link(f.attachment)}" target="_blank" rel="noopener">Open filing</a>` : ""}<a href="#/c/${c.symbol}">Open ledger</a></div></div></div>`)}
      </div></section>` : ""}

    ${material.length ? html`<section class="section">
      <h2>Worth knowing <span class="n">${material.length}</span></h2>
      <div class="ledger">${material.map((it) => materialRow(it))}</div></section>` : ""}

    ${n === 0 && !buried.length ? html`<div class="empty"><b>No filings in this window.</b>${s.window === "custom" ? "Try other dates above." : "Try a longer window above."}</div>` : ""}

    ${buried.length ? html`<section class="buried">
      <button type="button" aria-expanded="false" data-bury>
        <span class="count">${buried.length} filings buried</span>
        <span class="kinds">${buriedKinds(buried, LABELS).slice(0, 4).join(", ")}</span>
      </button>
      <ul hidden>${buried.map((it) => html`<li><span class="s">${it.symbol}</span>
        <span>${it.attachment ? html`<a href="${link(it.attachment)}" target="_blank" rel="noopener">${it.headline}</a>` : it.headline}
        <br><span style="color:var(--ink-3)">${LABELS[it.category] || it.category}, ${when(it.ts)}</span></span></li>`)}</ul>
    </section>` : ""}
  `);

  el.querySelectorAll("[data-win]").forEach((b) => b.addEventListener("click", () => {
    s.window = b.dataset.win; ctx.save(); todayView(el, ctx, _a, alive);
  }));
  el.querySelectorAll("[data-range]").forEach((inp) => inp.addEventListener("change", () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(inp.value)) return;
    s.range = { from, to, ...(s.range || {}), [inp.dataset.range]: inp.value };
    ctx.save(); todayView(el, ctx, _a, alive);
    el.querySelector(`[data-range="${inp.dataset.range}"]`)?.focus();
  }));
  const bury = el.querySelector("[data-bury]");
  bury?.addEventListener("click", () => {
    const open = bury.getAttribute("aria-expanded") === "true";
    bury.setAttribute("aria-expanded", String(!open));
    bury.nextElementSibling.hidden = open;
  });
}

const dayLabel = (d) => when(`${d}T15:30:00+05:30`);
const moveGlyph = (m) => raw(`<svg class="mk" viewBox="0 0 16 16" role="img" aria-label="${m.chg >= 0 ? "Up" : "Down"}"><path d="${m.chg >= 0 ? "M8 3l5 8H3z" : "M8 13L3 5h10z"}" fill="${m.chg >= 0 ? "var(--kept)" : "var(--miss)"}"/></svg>`);
const moveText = (m) => `${m.chg >= 0 ? "Up" : "Down"} ${Math.abs(m.chg).toFixed(1)}% on ${m.vx.toFixed(1)}× its usual volume.`;

function moveChip(m) {
  if (!m) return "";
  return html`<span class="chip ${m.chg >= 0 ? "up" : "down"}">Stock ${pct(m.chg)} on ${m.vx.toFixed(1)}× volume</span>`;
}

function who(it) {
  return html`<div class="who"><b>${it.symbol}</b> ${it.name}<span class="t">${when(it.ts)}</span></div>`;
}

function links(it, extra = []) {
  return html`<div class="links">
    ${it.attachment ? html`<a href="${link(it.attachment)}" target="_blank" rel="noopener">Open filing</a>` : ""}
    ${extra}
    <a href="#/c/${it.symbol}">Open ledger</a></div>`;
}

function promiseRow(it, names) {
  const card = it.card?.type === "results" ? it.card : null;
  let glyph = mark("on_track", "Bears on a promise");
  if (card) {
    const pc = card.promise_check || [];
    glyph = pc.some((p) => p.verdict === "below") ? mark("slipping", "Below a promise") : pc.length ? mark("on_track", "In line with promises") : mark("pending", "Results");
  } else if (it.promise_links?.some((l) => l.effect === "undermines")) {
    glyph = mark("slipping", "Undermines a promise");
  }
  const related = (it.related || []).filter((r) => r.attachment).map((r) =>
    html`<a href="${link(r.attachment)}" target="_blank" rel="noopener">${r.subtype === "deck" ? "Investor deck" : r.subtype === "ad" ? "Newspaper ad" : "Press release"}</a>`);
  return html`<div class="row"><div class="m">${glyph}</div><div class="b">
    ${who(it)}
    <p class="what">${card ? `${card.quarter || "Quarterly"} results` : it.summary || it.headline}</p>
    ${card ? resultsCard(card) : ""}
    ${(it.promise_links || []).map((l) => html`<div class="promise-ref">
      <div class="said">${l.statement}</div>
      <div class="effect">${l.effect === "undermines" ? mark("slipping") : mark("on_track")}<span>${l.note}</span></div></div>`)}
    ${it.move ? html`<div class="links">${moveChip(it.move)}</div>` : ""}
    ${links(it, related)}
  </div></div>`;
}

function deltaCell(d) {
  return html`<td class="${sign(d?.pct)}">${d?.pct != null ? pct(d.pct) : d?.label || "—"}</td>`;
}

function resultsCard(c) {
  if (!c.ok) return html`<p class="why">The results document could not be read: ${c.reason}.</p>`;
  return html`
    <table class="res">
      <thead><tr><th scope="col"><span class="sr">Line</span></th><th scope="col">${c.unit}</th><th scope="col">vs last qtr</th><th scope="col">vs last year</th></tr></thead>
      <tbody>${c.rows.map((r) => html`<tr><td>${r.label}</td><td class="v">${num(r.value)}</td>${deltaCell(r.qoq)}${deltaCell(r.yoy)}</tr>`)}</tbody>
    </table>
    ${c.ebitda_margin != null ? html`<p class="foot">EBITDA margin ${c.ebitda_margin.toFixed(1)}%. ${c.basis === "standalone" ? "Standalone figures." : ""}</p>` : ""}
    ${c.lender ? html`<p class="foot">${c.ebitda_note}</p>` : ""}
    ${c.promise_check?.length ? html`<div class="check">${c.promise_check.map((p) => html`<div>
      ${mark(p.verdict === "below" ? "slipping" : "on_track", p.verdict)}
      <span><span style="font-family:var(--serif)">${p.statement}</span><br><span class="foot">This quarter, against ${target({ ...p.target, unit: "%" })}</span></span>
      <span class="val ${p.verdict === "below" ? "neg" : "pos"}">${p.value.toFixed(1)}%</span></div>`)}</div>` : ""}
    ${c.filled_from_table?.length ? html`<p class="foot">${c.filled_from_table.join(", ").replace(/, ([^,]*)$/, " and $1")} taken from the exchange's quarterly data, because the filing could not be read cleanly for ${c.filled_from_table.length > 1 ? "them" : "it"}.</p>` : ""}
    ${c.cross_check === true ? html`<p class="foot">Revenue and profit match the exchange's quarterly data.</p>`
      : c.cross_check === false ? html`<p class="foot neg">These numbers differ from the exchange's quarterly data. Check the filing.</p>` : ""}
    ${c.note ? html`<p class="foot">${c.note}</p>` : ""}`;
}

/** Top management before the board; within each, arrivals before exits. */
const rank = (c) => (c.level === "top" ? 0 : 2) + (c.action === "appointed" ? 0 : 1);

function personLine(p) {
  const verb = { appointed: "In", resigned: "Out", retired: "Retiring", redesignated: "New role", ceased: "Out" }[p.action] || "Change";
  return html`<div class="person"><span class="n">${verb}: ${p.name}</span>, ${p.role}${p.effective ? html`<span class="foot"> from ${p.effective}</span>` : ""}
    ${p.background ? html`<p class="bio">${p.background}</p>`
      : p.web_background ? html`<p class="bio web">${p.web_background.text}<span class="foot"> The filing gave no profile; this is from a web search${(p.web_background.sources || []).map((s, i) => html`${i ? "," : ":"} <a href="${link(s.url)}" target="_blank" rel="noopener">${s.title}</a>`)}. Check it before relying on it.</span></p>` : ""}
    ${p.reason ? html`<p class="bio">Stated reason: ${p.reason}</p>` : ""}</div>`;
}

function materialRow(it) {
  if (it.card?.type === "people") {
    const changes = [...it.card.changes, ...((it.twins || []).flatMap((t) => t.card.changes))];
    const seen = new Set();
    const uniq = changes.filter((c) => { const k = c.name + c.action; if (seen.has(k)) return false; seen.add(k); return true; })
      .sort((a, b) => rank(a) - rank(b));
    const role = uniq.find((c) => c.level === "top")?.role || "Management";
    const short = role.replace(/Chief Financial Officer/i, "CFO").replace(/Chief Executive Officer/i, "CEO").replace(/Managing Director/i, "MD");
    return html`<div class="row"><div class="m">${entry("Management change")}</div><div class="b">
      ${who(it)}<p class="what">${short} change</p>
      ${uniq.map(personLine)}
      ${it.move ? html`<div class="links">${moveChip(it.move)}</div>` : ""}
      ${links(it)}</div></div>`;
  }
  return html`<div class="row"><div class="m">${entry(LABELS[it.category] || "Filing")}</div><div class="b">
    ${who(it)}
    <p class="what">${it.summary || it.headline}</p>
    ${it.why ? html`<p class="why">${it.why}</p>` : html`<p class="why">${LABELS[it.category] || it.category}${it.read_error ? ", not read: the filing could not be opened" : ""}</p>`}
    ${it.move ? html`<div class="links">${moveChip(it.move)}</div>` : ""}
    ${links(it)}</div></div>`;
}
