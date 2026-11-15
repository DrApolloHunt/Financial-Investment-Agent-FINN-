import * as data from "../data.js";
import { LABELS } from "../categories.js";
import { callQuestions, questionsText, tier } from "../logic.js";
import {
  avatar, barChart, crore, day, html, icon, lineChart, mark, mount, moveBadge, num, rupees, sparkline,
  link, STATUS, STATUS_ORDER, tag, target, when, wireChart,
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
  return html`<div class="prow" data-p="${p.id}">
    <div class="m">${mark(p.status)}</div>
    <div class="b" role="button" tabindex="0" aria-expanded="false">
      <div class="p-stmt">${p.statement}</div>
      <div class="p-meta">${STATUS[p.status]?.label}${t ? `, target ${t}` : ""}${p.horizon ? `, by ${p.horizon}` : ""}${p.revised === "worse" ? ", target cut" : p.revised === "better" ? ", target raised" : ""}</div>
      <div class="p-why ${alarm ? "alarm" : ""}">${p.reason}</div>
      <div class="p-more">
        ${p.quote ? html`<blockquote class="quote">“${p.quote}”<cite>${p.speaker || "Management"}, ${p.made_in} earnings call${p.source_url ? html`, <a href="${link(p.source_url)}" target="_blank" rel="noopener">transcript</a>` : ""}</cite></blockquote>` : ""}
        ${history(p)}
        ${p.actual ? html`<p class="actual">Delivered: <b>${num(p.actual.value)}${p.actual.unit === "%" ? "%" : p.actual.unit ? ` ${p.actual.unit}` : ""}</b> for ${p.actual.period}. <span class="foot">Source: ${p.actual.source}.</span></p>` : ""}
        ${p.verdict && !p.verdict.startsWith(p.statement) && p.verdict !== p.reason ? html`<p class="actual">${p.verdict}</p>` : ""}
      </div>
    </div>${icon("chev", "chev")}</div>`;
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
  const F = co.fundamentals;
  const T = F?.trajectory;
  const B = co.business && co.business.what_it_does ? co.business : null;
  const bull = L.bull || [], bear = L.bear || [];
  const asks = callQuestions(L.promises, L.latest_quarter);
  const jumps = [["promises", "Promises"], asks.length ? ["ask", "Ask on the call"] : null,
    bull.length || bear.length ? ["bullbear", "Bull vs bear"] : null,
    B ? ["business", "Business"] : null, F || rev.length ? ["numbers", "Numbers"] : null,
    F?.balance?.period ? ["balance", "Balance sheet"] : null, F?.cash?.years ? ["cash", "Cash quality"] : null].filter(Boolean);

  mount(el, html`
    ${back ? html`<div class="bar"><a class="iconbtn" href="${back}" aria-label="Back to ledgers">${icon("back")}</a><span class="crumb">Ledgers</span></div>` : ""}
    ${banner || ""}
    <section class="card cohero">
      <div class="cohead">${avatar(co.symbol, co.name, "lg")}
        <div><h1 class="title">${co.name}</h1><div class="meta">${co.symbol}${co.sector ? `, ${co.sector}` : ""}${co.basis ? `, ${co.basis} figures` : ""}</div></div>
      </div>
      ${last ? html`<div class="quote-row"><b>${rupees(last.c)}</b>${moveBadge(chg)}</div>` : ""}
      ${px.length > 2 ? html`${sparkline(px.map((p) => p.c))}<p class="foot">Closing prices, six months to ${day(last.d)}</p>` : ""}
    </section>

    ${L.credibility ? html`<section class="read-card"><span class="by">${icon("spark")}FINN's read of ${L.calls?.length || "the last"} earnings calls against reported numbers</span><p>${L.credibility}</p></section>` : ""}

    ${jumps.length > 2 ? html`<div class="jump-wrap"><nav class="chips" aria-label="On this page">${jumps.map(([id, label]) => html`<button type="button" data-jump="${id}">${label}</button>`)}</nav></div>` : ""}

    <section class="card sec-card" id="sec-promises">
      <h2>Promises <span class="n">${L.promises.length}</span></h2>
      ${L.promises.length ? html`<div class="tag-row">${STATUS_ORDER.filter((st) => L.counts?.[st]).map((st) => tag(st, `${L.counts[st]} ${STATUS[st].label.toLowerCase()}`))}</div>` : ""}
      ${L.promises.length ? html`<div class="plist">${groups.map(([st, ps]) => html`
          <div class="group-h">${tag(st, `${STATUS[st].label} (${ps.length})`)}</div>
          ${ps.map(promiseRow)}`)}</div>
          <p class="foot">Tap a promise for the quote, the call-by-call history and the filing that settled it.</p>`
        : html`<p class="note">${co.transcripts?.length ? "No forward-looking commitments were found in the calls read." : "No earnings-call transcripts are available for this company, so there is nothing to hold management to yet."}</p>`}
    </section>

    ${asks.length ? html`<section class="card sec-card" id="sec-ask">
      <h2>Ask on the next call <span class="n">${asks.length}</span></h2>
      <p class="lede">What to put to management, from what they promised and what happened since. Most pressing first.</p>
      <ol class="asks">${asks.map((q) => html`<li class="ask-${q.kind}">
        <p class="ask-q">${q.ask}</p>
        <blockquote class="ask-p">${q.statement}<cite>Promised on the ${q.made_in} call${q.source_url ? html`, <a href="${link(q.source_url)}" target="_blank" rel="noopener">transcript</a>` : ""}</cite></blockquote>
        ${q.facts.length ? html`<p class="ask-f">${q.facts.join(". ")}.</p>` : ""}
      </li>`)}</ol>
      <div class="card-f"><button type="button" class="pill primary" data-share-q>${icon("share")}<span>${"share" in navigator ? "Share questions" : "Copy questions"}</span></button></div>
    </section>` : ""}

    ${bull.length || bear.length ? html`<section class="card sec-card" id="sec-bullbear"><h2>Bull vs bear</h2>
      <div class="bb">
        <div class="bull"><h3>${icon("up")}Bull case</h3><ul>${bull.map((b) => html`<li>${b}</li>`)}</ul></div>
        <div class="bear"><h3>${icon("down")}Bear case</h3><ul>${bear.map((b) => html`<li>${b}</li>`)}</ul></div>
      </div>
      <p class="foot">Argued only from this page: the promise ledger, the reported numbers and the annual report.</p>
    </section>` : ""}

    ${B ? html`<section class="card sec-card" id="sec-business"><h2>Business</h2>
      <p class="said-block">${B.what_it_does}</p>
      ${B.segments?.length && !B.segments.some((g) => g.share_pct != null) ? html`<p class="foot">Segments</p>
        <div class="tag-row">${B.segments.map((g) => html`<span class="tag">${g.name}</span>`)}</div>` : ""}
      ${B.segments?.some((g) => g.share_pct != null) ? html`<div class="mix">${B.segments.filter((g) => g.share_pct != null).map((g) => html`<div class="mix-row">
        <span class="mix-name">${g.name}</span>
        <span class="mix-bar"><span style="width:${Math.max(2, Math.min(100, g.share_pct || 0))}%"></span></span>
        <span class="mix-val">${g.share_pct != null ? `${(+g.share_pct).toFixed(0)}%` : "—"}</span></div>`)}</div>
        <p class="foot">Share of revenue${B.mix_basis ? `, ${B.mix_basis}` : ""}.</p>` : ""}
      ${B.other_facts?.length ? html`<ul class="facts">${B.other_facts.map((x) => html`<li>${x}</li>`)}</ul>` : ""}
      <p class="foot">From the ${B.year || "latest"} annual report${B.url ? html`, <a href="${link(B.url)}" target="_blank" rel="noopener">open it</a>` : ""}.</p>
    </section>` : ""}

    ${F || rev.length ? html`<section class="card sec-card" id="sec-numbers"><h2>Numbers</h2>
      ${F ? html`<dl class="stats">
        ${stat(`Revenue, ${F.snapshot.period || "latest"}`, F.snapshot.revenue != null ? crore(F.snapshot.revenue) : null)}
        ${stat(`Net profit, ${F.snapshot.period || "latest"}`, F.snapshot.pat != null ? crore(F.snapshot.pat) : null)}
        ${stat("EBITDA margin", F.snapshot.margin != null ? `${F.snapshot.margin}%` : null)}
        ${stat("Market value", F.snapshot.market_cap_cr != null ? crore(F.snapshot.market_cap_cr) : null)}
        ${stat("Price / earnings", F.snapshot.pe != null ? `${F.snapshot.pe}×` : null)}
        ${stat("Return on equity", F.snapshot.roe != null ? `${F.snapshot.roe}%` : null)}
        ${stat("Return on capital", F.snapshot.roce != null ? `${F.snapshot.roce}%` : null)}
        ${stat("Dividend yield", F.snapshot.dividend_yield != null ? `${F.snapshot.dividend_yield}%` : null)}
      </dl>` : ""}
      ${T?.notes?.length ? html`<ul class="facts">${T.notes.map((n) => html`<li>${n}</li>`)}</ul>` : ""}
      <div class="seg" role="group" aria-label="Chart period">
        ${T?.years?.length ? html`<button type="button" data-span="y" aria-pressed="true">Ten years</button>` : ""}
        ${rev.length ? html`<button type="button" data-span="q" aria-pressed="${T?.years?.length ? "false" : "true"}">Twelve quarters</button>` : ""}
      </div>
      ${T?.years?.length ? html`<div class="charts" data-panel="y">
        <div class="chart"><h3>Revenue, ₹ crore</h3>${barChart("y-rev", T.years, T.revenue)}<div class="read"></div></div>
        <div class="chart"><h3>Net profit, ₹ crore</h3>${barChart("y-pat", T.years, T.pat)}<div class="read"></div></div>
        ${!co.is_lender && T.margin.some((m) => m != null) ? html`<div class="chart"><h3>EBITDA margin, %</h3>${lineChart("y-mar", T.years, T.margin)}<div class="read"></div></div>` : ""}
      </div>` : ""}
      ${rev.length ? html`<div class="charts" data-panel="q" ${T?.years?.length ? "hidden" : ""}>
        <div class="chart"><h3>Revenue, ₹ crore</h3>${barChart("c-rev", periods, rev)}<div class="read"></div></div>
        ${margin.some((m) => m != null) ? html`<div class="chart"><h3>${co.is_lender ? "Financing margin" : "EBITDA margin"}, %</h3>${lineChart("c-mar", periods, margin)}<div class="read"></div></div>` : ""}
      </div>` : ""}
      <p class="foot">Tap a bar or point to read its value. ${F ? F.source : "Exchange-reported quarterly figures."}</p>
    </section>` : ""}

    ${F?.balance?.period ? html`<section class="card sec-card" id="sec-balance"><h2>Balance sheet <span class="n">${F.balance.period}</span></h2>
      <dl class="stats">
        ${stat(F.balance.lender ? "Borrowings and deposits" : "Borrowings", F.balance.borrowings != null ? crore(F.balance.borrowings) : null)}
        ${stat("Net worth", F.balance.net_worth != null ? crore(F.balance.net_worth) : null)}
        ${stat("Debt / equity", F.balance.debt_to_equity != null ? `${F.balance.debt_to_equity}` : null)}
        ${stat("Interest cover", F.balance.interest_cover != null ? `${F.balance.interest_cover}×` : null)}
      </dl>
      ${F.balance.wc_days?.some((x) => x != null) ? html`<div class="chart"><h3>Working-capital days</h3>${lineChart("b-wc", F.balance.wc_years, F.balance.wc_days, { unit: "" })}<div class="read"></div></div>` : ""}
      ${F.balance.notes?.length ? html`<ul class="facts">${F.balance.notes.map((n) => html`<li>${n}</li>`)}</ul>` : ""}
    </section>` : ""}

    ${F?.cash?.years && F.cash.lender ? html`<section class="card sec-card" id="sec-cash"><h2>Cash quality</h2>
      ${F.cash.notes?.length ? html`<p class="note">${F.cash.notes[0]}</p>` : ""}
    </section>` : ""}
    ${F?.cash?.years && !F.cash.lender ? html`<section class="card sec-card" id="sec-cash"><h2>Cash quality</h2>
      <table class="res"><thead><tr><th scope="col">Year</th><th scope="col">Operating cash</th><th scope="col">Net profit</th><th scope="col">Cash / profit</th></tr></thead>
        <tbody>${F.cash.years.map((y, i) => {
          const c = F.cash.cfo[i], p = F.cash.pat[i];
          const r = c != null && p ? Math.round((c / p) * 100) : null;
          return html`<tr><td>${y}</td><td>${num(c)}</td><td>${num(p)}</td><td class="${r == null ? "flat" : r >= 90 ? "pos" : r >= 70 ? "flat" : "neg"}">${r == null ? "—" : `${r}%`}</td></tr>`;
        })}</tbody></table>
      <p class="foot">₹ crore. Operating cash flow against reported net profit, year by year.</p>
      ${F.cash.notes?.length ? html`<ul class="facts">${F.cash.notes.map((n) => html`<li>${n}</li>`)}</ul>` : ""}
    </section>` : ""}

    ${recent.length ? html`<section class="card sec-card"><h2>Recent filings that matter</h2>
      ${recent.map((it) => html`<div class="mini">
        <div class="k"><span>${LABELS[it.category] || it.category}</span><span>${when(it.ts)}</span></div>
        <p>${it.summary || it.headline}</p>
        ${it.attachment ? html`<a href="${link(it.attachment)}" target="_blank" rel="noopener">Open filing</a>` : ""}</div>`)}
    </section>` : ""}

    <section class="card sec-card"><h2>Sources</h2>
      <p class="src">Promises come only from the company's own earnings-call transcripts${L.calls?.length ? ":" : "."}
        ${(L.calls || []).map((c, i) => html`${i ? ", " : " "}<a href="${link(c.url)}" target="_blank" rel="noopener">${c.quarter}</a>`)}.
        Delivered numbers and the ten-year figures come from the company's filings${co.url ? html` via <a href="${link(co.url)}" target="_blank" rel="noopener">screener.in</a>` : ""}.
        ${B ? html`The business snapshot is read from the ${B.year || "latest"} annual report. ` : ""}No news, broker notes or model memory are used.${L.verdict_model ? ` Verdicts and the bull and bear cases written by ${L.verdict_model}.` : ""}</p>
    </section>
  `);

  el.querySelectorAll(".prow > .b").forEach((b) => {
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
  if (T?.years?.length) {
    wireChart(el, "y-rev", T.years, T.revenue, (v) => crore(v));
    wireChart(el, "y-pat", T.years, T.pat, (v) => crore(v));
    wireChart(el, "y-mar", T.years, T.margin, (v) => `${v.toFixed(1)}%`);
  }
  if (F?.balance?.wc_days) wireChart(el, "b-wc", F.balance.wc_years, F.balance.wc_days, (v) => `${v.toFixed(0)} days`);
  el.querySelectorAll("[data-span]").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("[data-span]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    el.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== b.dataset.span; });
  }));
  el.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => {
    el.querySelector(`#sec-${b.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  el.querySelector("[data-share-q]")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget, label = btn.querySelector("span");
    const text = questionsText(co.name, asks);
    try {
      if (navigator.share) {
        await navigator.share({ title: `Questions for ${co.name}`, text });
        return;
      }
    } catch (err) {
      if (err?.name === "AbortError") return;   // the investor closed the share sheet
    }
    const ok = await copyText(text);
    label.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(() => { label.textContent = "Copy questions"; }, 2000);
  });
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  const ta = Object.assign(document.createElement("textarea"), { value: text });
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.append(ta); ta.select();
  const ok = document.execCommand?.("copy") ?? false;
  ta.remove();
  return ok;
}

function stat(label, value) {
  if (value == null) return "";
  return html`<div><dt>${label}</dt><dd>${value}</dd></div>`;
}
