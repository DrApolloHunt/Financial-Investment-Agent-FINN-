import * as data from "../data.js";
import { LABELS } from "../categories.js";
import { buriedKinds, explaining, group, istDate, tier, unusual, windowRange } from "../logic.js";
import { ago, avatar, html, icon, link, logo, mark, mount, moveBadge, nowMs, num, pct, sign, stampOf, tag, target, today, when } from "../ui.js";

const WINDOWS = [["24h", "24 hours"], ["3d", "3 days"], ["7d", "7 days"], ["since", "Since last visit"], ["custom", "Dates"]];

export async function todayView(el, ctx, _a, alive) {
  const [meta, port, feed] = await Promise.all([
    data.meta().catch(() => null), data.portfolio().catch(() => null), data.feed().catch(() => null)]);
  if (!alive()) return;
  if (!feed || !port) {
    return mount(el, html`${topbar(null)}
      <div class="empty"><b>No filings collected yet.</b>FINN fills this page from exchange filings and prices once the data refresh has run.</div>`);
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

  const tiles = [
    ["promise", "t-promise", "flag", promise.length, "Promises"],
    ["move", "t-move", "pulse", unexplained.length + movedWith.length, "Price moves"],
    ["know", "t-know", "bell", material.length, "Worth knowing"],
    ["buried", "t-buried", "box", buried.length, "Buried"],
  ];

  mount(el, html`
    ${topbar(port)}
    <section class="hello">
      <p class="date">${today()}</p>
      <h1 class="hero">${hero} <span class="quiet">${buried.length} buried.</span></h1>
      ${s.window === "since" && !ctx.session.start ? html`<p class="sub">First visit: showing the last 24 hours.</p>` : ""}
      ${meta?.generated_at && !ctx.snapshot ? html`<p class="sub">Data updated ${ago(meta.generated_at)}.</p>` : ""}
    </section>
    <div class="chips" role="group" aria-label="Time window">
      ${WINDOWS.map(([k, label]) => html`<button type="button" data-win="${k}" aria-pressed="${s.window === k}">${k === "custom" ? icon("calendar") : ""}${label}</button>`)}
    </div>
    ${s.window === "custom" ? html`<div class="range">
      <label>From <input type="date" data-range="from" value="${from}" min="${istDate(Date.parse(earliest))}" max="${istDate(now)}"></label>
      <label>to <input type="date" data-range="to" value="${to}" min="${istDate(Date.parse(earliest))}" max="${istDate(now)}"></label>
      <p class="foot">Filings collected from ${when(earliest)}.</p></div>` : ""}

    <div class="tiles">${tiles.map(([id, cls, ic, count, label]) => html`<button type="button" class="tile" data-go="${id}" ${count ? "" : "disabled"}>
      <span class="ti ${cls}">${icon(ic)}</span><b>${count}</b><span>${label}</span></button>`)}</div>

    ${ctx.snapshot ? html`<p class="banner">${icon("info")}<span>Demo snapshot: filings and prices as of ${stampOf(meta.as_of || meta.generated_at)}, so "the last 24 hours" means the 24 hours before it. Research works live on any company.</span></p>` : ""}
    ${data.FIXTURES ? html`<p class="banner">${icon("info")}<span>Sample data: these companies, filings and quotes are fictional.</span></p>` : ""}
    ${stale ? html`<p class="banner">${icon("info")}<span>The last data refresh was ${ago(meta.generated_at)}. Filings since then are not shown.</span></p>` : ""}

    ${promise.length ? html`<section class="section" id="go-promise">
      <div class="sec-h"><h2>Moves a promise</h2><span class="count">${promise.length}</span></div>
      <p class="lede">Results, and filings that bear on something management promised.</p>
      <div class="cards">${promise.map((it) => promiseCard(it))}</div></section>` : ""}

    ${unexplained.length || movedWith.length ? html`<section class="section" id="go-move">
      <div class="sec-h"><h2>Price moved</h2><span class="count">${unexplained.length + movedWith.length}</span></div>
      <p class="lede">Beyond ${s.movePct}% in a day or ${s.volX}× the usual volume, by your settings.</p>
      <div class="cards">
        ${unexplained.map(({ c, m }) => moveCard(c, m, null))}
        ${movedWith.map(({ c, m, f }) => moveCard(c, m, f))}
      </div></section>` : ""}

    ${material.length ? html`<section class="section" id="go-know">
      <div class="sec-h"><h2>Worth knowing</h2><span class="count">${material.length}</span></div>
      <div class="cards">${material.map((it) => materialCard(it))}</div></section>` : ""}

    ${n === 0 && !buried.length ? html`<div class="empty"><b>No filings in this window.</b>${s.window === "custom" ? "Try other dates above." : "Try a longer window above."}</div>` : ""}

    ${buried.length ? html`<section class="buried" id="go-buried">
      <button type="button" aria-expanded="false" data-bury>
        <span class="bi">${icon("box")}</span>
        <span class="bcount">${buried.length} filings buried</span>
        ${icon("chev", "chev")}
        <span class="kinds">${buriedKinds(buried, LABELS).slice(0, 4).join(", ")}</span>
      </button>
      <ul hidden>${buried.map((it) => html`<li><span class="s">${it.symbol}</span>
        <span>${it.attachment ? html`<a href="${link(it.attachment)}" target="_blank" rel="noopener">${it.headline}</a>` : it.headline}
        <br><span class="k">${LABELS[it.category] || it.category}, ${when(it.ts)}</span></span></li>`)}</ul>
    </section>` : ""}
  `);

  el.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => {
    const target = el.querySelector(`#go-${b.dataset.go}`);
    if (b.dataset.go === "buried") {
      const btn = target?.querySelector("[data-bury]");
      if (btn?.getAttribute("aria-expanded") === "false") btn.click();
    }
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
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

function topbar(port) {
  const n = port?.companies?.length || 0;
  return html`<header class="top">
    <div class="brandrow">
      <a class="logo" href="#/" aria-label="FINN home">${logo()}<span class="wm">FINN</span></a>
      ${n ? html`<span class="where"><b>My portfolio</b><span>${n} companies</span></span>` : ""}
      <a class="iconbtn" href="#/settings" aria-label="Settings">${icon("sliders")}</a>
    </div>
    <a class="search" href="#/research">${icon("search")}<span>Research any NSE company</span></a>
  </header>`;
}

function cardHead(it) {
  return html`<div class="card-h">${avatar(it.symbol, it.name)}
    <div class="id"><b>${it.symbol}</b><span>${it.name}</span></div><time>${when(it.ts)}</time></div>`;
}

/** The status tag, with the day's price move beside it like a rating badge. */
function tags(it, t) {
  return html`<div class="tag-row">${t}${it.move ? html`<span class="mv">${moveBadge(it.move.chg)}<span class="badge-note">${it.move.vx.toFixed(1)}× volume</span></span>` : ""}</div>`;
}

function actions(it, extra = []) {
  return html`
    ${extra.length ? html`<p class="foot">Also filed: ${extra.map((a, i) => html`${i ? ", " : ""}${a}`)}.</p>` : ""}
    <div class="card-f">
    ${it.attachment ? html`<a class="pill" href="${link(it.attachment)}" target="_blank" rel="noopener">${icon("doc")}Filing</a>` : ""}
    <a class="pill primary" href="#/c/${it.symbol}">${icon("book")}Ledger</a></div>`;
}

function moveCard(c, m, f) {
  return html`<article class="card">
    <div class="card-h">${avatar(c.symbol, c.name)}<div class="id"><b>${c.symbol}</b><span>${c.name}</span></div><time>${dayLabel(m.d)}</time></div>
    <div class="tag-row">${f ? tag("on_track", "Filing found") : tag("slipping", "No filing explains it")}<span class="mv">${moveBadge(m.chg)}<span class="badge-note">${m.vx.toFixed(1)}× volume</span></span></div>
    <h3 class="card-t">${m.chg >= 0 ? "Up" : "Down"} ${Math.abs(m.chg).toFixed(1)}% on ${m.vx.toFixed(1)}× its usual volume</h3>
    ${f ? html`<p class="card-p">Filed before this window: ${f.summary || f.headline}</p>`
      : html`<p class="card-p">Nothing was filed since the previous close. The price may know something the filings don't say.</p>`}
    <div class="card-f">
      ${f?.attachment ? html`<a class="pill" href="${link(f.attachment)}" target="_blank" rel="noopener">${icon("doc")}Filing</a>` : ""}
      <a class="pill primary" href="#/c/${c.symbol}">${icon("book")}Ledger</a></div>
  </article>`;
}

function promiseCard(it) {
  const card = it.card?.type === "results" ? it.card : null;
  let t = tag("on_track", "Bears on a promise");
  if (card) {
    const pc = card.promise_check || [];
    t = pc.some((p) => p.verdict === "below") ? tag("slipping", "Below a promise") : pc.length ? tag("on_track", "In line with promises") : tag("pending", "Results");
  } else if (it.promise_links?.some((l) => l.effect === "undermines")) {
    t = tag("slipping", "Undermines a promise");
  }
  const related = (it.related || []).filter((r) => r.attachment).map((r) =>
    html`<a href="${link(r.attachment)}" target="_blank" rel="noopener">${r.subtype === "deck" ? "investor deck" : r.subtype === "ad" ? "newspaper ad" : "press release"}</a>`);
  return html`<article class="card">
    ${cardHead(it)}
    ${tags(it, t)}
    <h3 class="card-t">${card ? `${card.quarter || "Quarterly"} results` : it.summary || it.headline}</h3>
    ${card ? resultsCard(card) : ""}
    ${(it.promise_links || []).map((l) => html`<div class="promise-ref">
      <div class="said">${l.statement}</div>
      <div class="effect">${l.effect === "undermines" ? mark("slipping") : mark("on_track")}<span>${l.note}</span></div></div>`)}
    ${actions(it, related)}
  </article>`;
}

function deltaCell(d) {
  return html`<td class="${sign(d?.pct)}">${d?.pct != null ? pct(d.pct) : d?.label || "—"}</td>`;
}

function resultsCard(c) {
  if (!c.ok) return html`<p class="card-p">The results document could not be read: ${c.reason}.</p>`;
  return html`
    <div class="res-wrap"><table class="res">
      <thead><tr><th scope="col"><span class="sr">Line</span></th><th scope="col">${c.unit}</th><th scope="col">vs last qtr</th><th scope="col">vs last year</th></tr></thead>
      <tbody>${c.rows.map((r) => html`<tr><td>${r.label}</td><td class="v">${num(r.value)}</td>${deltaCell(r.qoq)}${deltaCell(r.yoy)}</tr>`)}</tbody>
    </table></div>
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
  const cls = p.action === "appointed" ? "in" : ["resigned", "ceased", "retired"].includes(p.action) ? "out" : "";
  return html`<div class="person"><span class="verb ${cls}">${verb}</span><span class="n">${p.name}</span><span class="role">, ${p.role}</span>${p.effective ? html`<span class="when">From ${p.effective}</span>` : ""}
    ${p.background ? html`<p class="bio">${p.background}</p>`
      : p.web_background ? html`<p class="bio web">${p.web_background.text}<span class="foot">The filing gave no profile; this is from a web search${(p.web_background.sources || []).map((s, i) => html`${i ? "," : ":"} <a href="${link(s.url)}" target="_blank" rel="noopener">${s.title}</a>`)}. Check it before relying on it.</span></p>` : ""}
    ${p.reason ? html`<p class="bio">Stated reason: ${p.reason}</p>` : ""}</div>`;
}

function materialCard(it) {
  if (it.card?.type === "people") {
    const changes = [...it.card.changes, ...((it.twins || []).flatMap((t) => t.card.changes))];
    const seen = new Set();
    const uniq = changes.filter((c) => { const k = c.name + c.action; if (seen.has(k)) return false; seen.add(k); return true; })
      .sort((a, b) => rank(a) - rank(b));
    const role = uniq.find((c) => c.level === "top")?.role || "Management";
    const short = role.replace(/Chief Financial Officer/i, "CFO").replace(/Chief Executive Officer/i, "CEO").replace(/Managing Director/i, "MD");
    return html`<article class="card">
      ${cardHead(it)}
      ${tags(it, html`<span class="tag">Management change</span>`)}
      <h3 class="card-t">${short} change</h3>
      <div style="margin-top:12px">${uniq.map(personLine)}</div>
      ${actions(it)}</article>`;
  }
  return html`<article class="card">
    ${cardHead(it)}
    ${tags(it, html`<span class="tag">${LABELS[it.category] || "Filing"}</span>`)}
    <h3 class="card-t">${it.summary || it.headline}</h3>
    ${it.why ? html`<p class="card-p">${it.why}</p>` : it.read_error ? html`<p class="card-p">Not read: the filing could not be opened.</p>` : ""}
    ${actions(it)}</article>`;
}
