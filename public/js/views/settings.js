import * as data from "../data.js";
import { CATEGORIES } from "../categories.js";
import { ago, html, mount, num } from "../ui.js";

export async function settingsView(el, ctx, _a, alive) {
  const meta = await data.meta().catch(() => null);
  if (!alive()) return;
  const s = ctx.settings;
  const runs = meta?.usage_history || [];
  const total = runs.reduce((a, r) => { for (const [m, n] of Object.entries(r.calls || {})) a[m] = (a[m] || 0) + n; return a; }, {});
  const tokens = runs.reduce((a, r) => a + (r.tokens_in || 0) + (r.tokens_out || 0), 0);
  const fs = meta?.filter_stats;

  mount(el, html`
    <header class="head"><h1 class="title">Settings</h1></header>

    <section class="section"><h2>What counts as an unusual move</h2>
      <div class="set"><span>Price move in a day</span>
        <span class="step"><button type="button" data-k="movePct" data-d="-0.5" aria-label="Lower">−</button><output>±${s.movePct}%</output><button type="button" data-k="movePct" data-d="0.5" aria-label="Raise">+</button></span>
        <span class="d">Daily close against the previous close.</span></div>
      <div class="set"><span>Volume against its average</span>
        <span class="step"><button type="button" data-k="volX" data-d="-0.5" aria-label="Lower">−</button><output>${s.volX}×</output><button type="button" data-k="volX" data-d="0.5" aria-label="Raise">+</button></span>
        <span class="d">Compared with the previous 20 trading days.</span></div>
    </section>

    <section class="section"><h2>Filings I care about</h2>
      <p class="lede">Anything that bears on a management promise is always shown. These decide the rest.</p>
      ${CATEGORIES.map((c) => html`<div class="set"><label for="c-${c.id}">${c.label}</label>
        <span class="switch"><input type="checkbox" id="c-${c.id}" data-cat="${c.id}" ${s.care[c.id] ? "checked" : ""}><span></span></span>
        <span class="d">${c.desc}</span></div>`)}
    </section>

    <section class="section prose"><h2>How FINN decides</h2>
      <p><b>Promises first.</b> FINN reads each company's last five earnings calls and writes down every specific thing management committed to: growth, margins, capacity, orders, dates. Each later call is checked for whether they repeated it, changed it, delivered it, or stopped mentioning it.</p>
      <p><b>Then the filings.</b> Results are always shown, with the headline numbers checked against open promises. Any other filing that bears on a promise is shown with it. Filings in the categories you care about come next. Everything else is buried, but counted and one tap away.</p>
      <p><b>Price moves are paired with filings.</b> A move with a filing behind it is shown on that filing. A move with no filing since the previous close is shown on its own, because the price knows something the filings don't say.</p>
    </section>

    ${fs ? html`<section class="section"><h2>Last 30 days, by the default rules</h2>
      <table class="usage"><tbody>
        <tr><td>Filings collected</td><td>${num(fs.filings)}</td></tr>
        <tr><td>Buried</td><td>${fs.buried_pct}%</td></tr>
        <tr><td>Filings on a typical day</td><td>${fs.median_filings_per_day}</td></tr>
        <tr><td>Unusual price moves</td><td>${fs.unusual_moves}</td></tr>
        <tr><td>Moves no filing explains</td><td>${fs.unexplained_moves}</td></tr>
      </tbody></table></section>` : ""}

    ${meta ? html`<section class="section"><h2>Data and cost</h2>
      <table class="usage"><tbody>
        <tr><td>Last refresh</td><td>${ago(meta.generated_at)}</td></tr>
        ${Object.entries(total).map(([m, n]) => html`<tr><td>${m} calls, recent runs</td><td>${num(n)}</td></tr>`)}
        <tr><td>Tokens processed</td><td>${num(tokens)}</td></tr>
        <tr><td>Spend</td><td>₹0 (free tier)</td></tr>
      </tbody></table>
      <p class="foot">Each document is read by a model once and cached. Bulk reading uses the cheapest model; only the per-company verdict uses a stronger one.</p>
      ${meta.errors?.length ? html`<details style="margin-top:10px"><summary class="foot">${meta.errors.length} source problems in the last run</summary>
        <ul class="foot">${meta.errors.map((e) => html`<li>${e}</li>`)}</ul></details>` : ""}
    </section>` : ""}

    <p style="margin-top:24px"><button class="btn ghost" type="button" data-reset>Restore defaults</button></p>
  `);

  el.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k, lim = k === "movePct" ? [0.5, 20] : [1.5, 10];
    s[k] = Math.min(lim[1], Math.max(lim[0], +(s[k] + +b.dataset.d).toFixed(1)));
    ctx.save();
    b.parentElement.querySelector("output").textContent = k === "movePct" ? `±${s[k]}%` : `${s[k]}×`;
  }));
  el.querySelectorAll("[data-cat]").forEach((i) => i.addEventListener("change", () => {
    s.care[i.dataset.cat] = i.checked; ctx.save();
  }));
  el.querySelector("[data-reset]").addEventListener("click", () => {
    Object.assign(s, { ...data.DEFAULTS, care: Object.fromEntries(CATEGORIES.map((c) => [c.id, c.care])) });
    ctx.save(); settingsView(el, ctx, _a, alive);
  });
}
