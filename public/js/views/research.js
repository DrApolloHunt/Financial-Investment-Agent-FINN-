import * as data from "../data.js";
import { html, mark, mount } from "../ui.js";
import { renderCompany } from "./company.js";

export async function researchView(el, ctx, sym, alive) {
  const port = await data.portfolio().catch(() => ({ companies: [], research: [] }));
  if (!alive()) return;
  const picks = port.research || [];

  mount(el, html`
    <header class="head">
      <h1 class="title">Research any company</h1>
      <p class="sub">FINN reads the last five earnings-call transcripts and the latest annual report, lists what management promised, checks each promise against reported numbers, and argues the bull and bear case from that evidence alone.</p>
      <form class="ask" autocomplete="off">
        <label class="sr" for="sym">NSE symbol</label>
        <input id="sym" name="sym" placeholder="NSE symbol, e.g. ASIANPAINT" value="${sym || ""}" spellcheck="false" autocapitalize="characters" inputmode="text">
        <button class="btn" type="submit">Build ledger</button>
      </form>
      ${picks.length ? html`<div class="picks">${picks.map((p) => html`<button type="button" data-pick="${p}">${p}</button>`)}</div>` : ""}
    </header>
    <div id="out"></div>`);

  const out = el.querySelector("#out");
  const go = (s) => { location.hash = `#/research/${s}`; };
  el.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = el.querySelector("#sym").value.trim().toUpperCase().replace(/\.(NS|BO)$/, "");
    if (v) go(v);
  });
  el.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => go(b.dataset.pick)));
  if (!sym) return;
  await build(out, ctx, sym, alive);
}

async function build(out, ctx, sym, alive) {
  const cached = data.cachedResearch(sym);
  if (cached) return renderCompany(out, cached, [], ctx, { banner: html`<p class="banner">Built on this device earlier this week.</p>` });

  const lines = [];
  let name = sym;
  const paint = (extra = "") => {
    if (!alive()) return;
    const rows = lines.map((l, i) => html`<div class="row ${i === lines.length - 1 ? "writing" : ""} ${l.live ? "live" : ""}"><div class="m">${mark(l.status)}</div><div class="b">${l.text}</div></div>`);
    mount(out, html`<section class="section progress"><h2>${name}</h2><div class="ledger">${rows}</div>${extra}</section>`);
  };
  const add = (status, text, live = false) => { lines.push({ status, text, live }); paint(); };
  const replaceLast = (status, text) => { lines.pop(); add(status, text); };

  add("pending", "Finding the company and its documents…", true);
  try {
    const co = await data.research(sym, (ev) => {
      if (ev.type === "company") {
        name = ev.co.name;
        replaceLast("kept", `Found ${ev.co.transcripts.length} earnings calls and ${ev.co.quarters.periods.length} quarters of reported numbers.`);
      } else if (ev.type === "reading") {
        add("pending", `Reading the ${ev.t.quarter} call…`, true);
      } else if (ev.type === "read") {
        replaceLast("kept", `${ev.t.quarter}: ${ev.found} new ${ev.found === 1 ? "promise" : "promises"}${ev.updated ? `, ${ev.updated} earlier ${ev.updated === 1 ? "one" : "ones"} updated` : ""}.`);
      } else if (ev.type === "readfail") {
        replaceLast("missed", `${ev.t.quarter}: could not be read. ${ev.error}`);
      } else if (ev.type === "business") {
        add("pending", "Reading the latest annual report…", true);
      } else if (ev.type === "businessread") {
        replaceLast("kept", `Annual report ${ev.business.year || ""}: ${ev.business.segments?.length || 0} segments found.`);
      } else if (ev.type === "businessfail") {
        replaceLast("missed", `The annual report could not be read. ${ev.error}`);
      } else if (ev.type === "judging") {
        add("pending", "Checking each promise against reported numbers and weighing the bull and bear cases…", true);
      } else if (ev.type === "nocalls") {
        replaceLast("dropped", "No earnings-call transcripts are listed for this company.");
      }
    });
    if (!alive()) return;
    renderCompany(out, co, [], ctx, {});
  } catch (e) {
    if (!alive()) return;
    paint(html`<p class="err">${e.message}</p>`);
  }
}
