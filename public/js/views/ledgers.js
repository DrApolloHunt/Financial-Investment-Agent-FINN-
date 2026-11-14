import * as data from "../data.js";
import { avatar, countsLine, html, mount, nowMs, pct, rupees, sign, strip, tag, STATUS_ORDER } from "../ui.js";

const FILTERS = [["all", "All"], ["off", "Off track"], ["fine", "On track"], ["new", "New filings"], ["none", "No guidance"]];

export async function ledgersView(el, ctx, _a, alive) {
  const [port, feed] = await Promise.all([data.portfolio(), data.feed().catch(() => ({ items: [] }))]);
  if (!alive()) return;
  // companies with a promise-moving filing in the last 3 days first, then by trouble
  const recent = new Set(feed.items.filter((it) => it.tier === "promise" && nowMs() - new Date(it.ts) < 3 * 864e5).map((it) => it.symbol));
  const trouble = (c) => (c.counts?.missed || 0) * 3 + (c.counts?.slipping || 0) * 2 + (c.counts?.dropped || 0) * 2;
  const list = [...port.companies].sort((a, b) => (recent.has(b.symbol) - recent.has(a.symbol)) || trouble(b) - trouble(a) || a.name.localeCompare(b.name));
  const detail = await Promise.all(list.map((c) => data.company(c.symbol).catch(() => null)));
  if (!alive()) return;

  const rows = list.map((c, i) => {
    const ps = detail[i]?.ledger?.promises || [];
    const bad = (c.counts?.missed || 0) + (c.counts?.slipping || 0) + (c.counts?.dropped || 0);
    const kind = !ps.length ? "none" : bad ? "off" : "fine";
    return { c, ps, bad, kind, fresh: recent.has(c.symbol) };
  });
  const count = (f) => (f === "all" ? rows.length : f === "new" ? rows.filter((r) => r.fresh).length : rows.filter((r) => r.kind === f).length);
  let filter = ctx.ledgerFilter || "all";

  const paint = () => {
    const shown = rows.filter((r) => filter === "all" || (filter === "new" ? r.fresh : r.kind === filter));
    mount(el, html`
      <header class="pagehead">
        <h1 class="title">Ledgers</h1>
        <p class="sub">What management promised on its last five earnings calls, and what happened to each promise.</p>
      </header>
      <div class="chips" role="group" aria-label="Show">
        ${FILTERS.filter(([f]) => f === "all" || count(f)).map(([f, label]) => html`<button type="button" data-f="${f}" aria-pressed="${filter === f}">${label}<span class="n">${count(f)}</span></button>`)}
      </div>
      <div class="legend" aria-label="What the marks mean">${STATUS_ORDER.map((s) => tag(s))}</div>
      <div class="cards spaced">
        ${shown.map(({ c, ps, bad, kind, fresh }) => html`<a class="card link" href="#/c/${c.symbol}">
          <div class="co">
            ${avatar(c.symbol, c.name)}
            <span class="nmw"><span class="nm">${c.name}</span><span class="sec">${c.symbol}${c.sector ? `, ${c.sector}` : ""}</span></span>
            <span class="px">${c.close != null ? rupees(c.close) : ""}<span class="${sign(c.chg)}">${c.chg != null ? pct(c.chg) : ""}</span></span>
          </div>
          <div class="co-b">
            ${ps.length ? strip(ps) : ""}
            <div class="tag-row flush">
              ${kind === "none" ? tag("pending", "No numeric guidance on record") : kind === "off" ? tag(c.counts?.missed ? "missed" : "slipping", `${bad} off track`) : tag("kept", "Nothing off track")}
              ${fresh ? html`<span class="tag" style="--c:var(--brand)">New filing on a promise</span>` : ""}
            </div>
            ${ps.length ? html`<span class="cnt">${countsLine(c.counts)}</span>` : ""}
          </div>
        </a>`)}
      </div>
      ${port.research?.length ? html`<p class="sub after">Also prepared for research: ${port.research.map((s, i) => html`${i ? ", " : ""}<a href="#/research/${s}">${s}</a>`)}.</p>` : ""}
    `);
    el.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => {
      filter = ctx.ledgerFilter = b.dataset.f;
      paint();
    }));
  };
  paint();
}
