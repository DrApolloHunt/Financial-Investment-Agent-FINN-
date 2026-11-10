import * as data from "../data.js";
import { countsLine, html, mount, pct, rupees, sign, strip, STATUS, STATUS_ORDER, mark } from "../ui.js";

export async function ledgersView(el, ctx, _a, alive) {
  const [port, feed] = await Promise.all([data.portfolio(), data.feed().catch(() => ({ items: [] }))]);
  if (!alive()) return;
  // companies with a promise-moving filing in the last 3 days first, then by trouble
  const recent = new Set(feed.items.filter((it) => it.tier === "promise" && Date.now() - new Date(it.ts) < 3 * 864e5).map((it) => it.symbol));
  const trouble = (c) => (c.counts?.missed || 0) * 3 + (c.counts?.slipping || 0) * 2 + (c.counts?.dropped || 0) * 2;
  const list = [...port.companies].sort((a, b) => (recent.has(b.symbol) - recent.has(a.symbol)) || trouble(b) - trouble(a) || a.name.localeCompare(b.name));
  const detail = await Promise.all(list.map((c) => data.company(c.symbol).catch(() => null)));
  if (!alive()) return;

  mount(el, html`
    <header class="head">
      <h1 class="title">Ledgers</h1>
      <p class="sub">Every promise management made on its last five earnings calls, and what happened to it. One mark per promise, oldest first.</p>
      <div class="legend" style="margin-top:10px">${STATUS_ORDER.map((s) => html`<span>${mark(s)}${STATUS[s].label}</span>`)}</div>
    </header>
    <div style="margin-top:14px">
      ${list.map((c, i) => {
        const ps = detail[i]?.ledger?.promises || [];
        return html`<a class="co" href="#/c/${c.symbol}">
          <span class="nm">${c.name}</span>
          <span class="px">${c.close != null ? rupees(c.close) : ""} <span class="${sign(c.chg)}">${c.chg != null ? pct(c.chg) : ""}</span></span>
          <span class="sec">${c.symbol}, ${c.sector}</span><span></span>
          <span class="cnt">${ps.length ? strip(ps) : ""}<span>${ps.length ? countsLine(c.counts) : "No promises on record yet"}</span></span>
          ${recent.has(c.symbol) ? html`<span class="flag">New filing bears on a promise</span>` : ""}
        </a>`;
      })}
    </div>
    ${port.research?.length ? html`<p class="sub" style="margin-top:22px">Also prepared for research: ${port.research.map((s, i) => html`${i ? ", " : ""}<a href="#/research/${s}">${s}</a>`)}.</p>` : ""}
  `);
}
