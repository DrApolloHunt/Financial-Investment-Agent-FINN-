import * as data from "./data.js";
import { html, mount, setNow } from "./ui.js";
import { CATEGORIES } from "./categories.js";
import { todayView } from "./views/today.js";
import { ledgersView } from "./views/ledgers.js";
import { companyView } from "./views/company.js";
import { researchView } from "./views/research.js";
import { settingsView } from "./views/settings.js";

const view = document.getElementById("view");

const settings = data.loadSettings();
if (!settings.care) settings.care = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.care]));
const ctx = {
  settings,
  save() { data.saveSettings(settings); },
  session: data.session(),
};

const routes = [
  [/^#?\/?$/, "today", todayView],
  [/^#\/ledgers$/, "ledgers", ledgersView],
  [/^#\/c\/([A-Za-z0-9&-]+)$/, "ledgers", companyView],
  [/^#\/research(?:\/([A-Za-z0-9&-]+))?$/, "research", researchView],
  [/^#\/settings(?:\/(alerts))?$/, "settings", settingsView],
];

let token = 0;
async function route() {
  const h = location.hash || "#/";
  const hit = routes.find(([rx]) => rx.test(h)) || routes[0];
  const [, tab, fn] = hit;
  const args = h.match(hit[0])?.slice(1) || [];
  document.querySelectorAll(".tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  const mine = ++token;
  try {
    await fn(view, ctx, args[0] ? args[0].toUpperCase() : undefined, () => mine === token);
  } catch (e) {
    console.error(e);
    if (mine === token) {
      mount(view, html`<div class="empty"><b>This view could not load.</b>${e.message}. Reload the page, or try again in a minute.</div>`);
    }
  }
  if (mine === token) {
    window.scrollTo(0, 0);
    view.focus({ preventScroll: true });
  }
}

window.addEventListener("hashchange", route);
data.meta().then((m) => {
  ctx.snapshot = Boolean(m?.snapshot && m.generated_at);
  if (ctx.snapshot) setNow(Date.parse(m.as_of || m.generated_at));
}).catch(() => {}).finally(route);

// A tab left open stays current: refetch when it comes back after 10 minutes,
// and every 15 minutes while it is visible. Data refreshes hourly upstream.
let loadedAt = Date.now();
const refresh = () => { if (ctx.snapshot) return; data.reset(); loadedAt = Date.now(); if (!location.hash.startsWith("#/research")) route(); };
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - loadedAt > 10 * 60e3) refresh();
});
setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 15 * 60e3);
