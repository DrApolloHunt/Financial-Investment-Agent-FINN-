import test from "node:test";
import assert from "node:assert/strict";
import { tier, unusual, explaining, group, windowStart, windowRange, buriedKinds } from "../../public/js/logic.js";

const care = { results: true, press_release: true, management_change: true, unclassified: false };

test("tier: promise links and results beat settings", () => {
  assert.equal(tier({ category: "results", subtype: "financials" }, {}), "promise");
  assert.equal(tier({ category: "press_release", subtype: "news", promise_links: [{}] }, {}), "promise");
  assert.equal(tier({ category: "press_release", subtype: "news" }, care), "material");
  assert.equal(tier({ category: "press_release", subtype: "news", importance: "low" }, care), "routine");
  assert.equal(tier({ category: "results", subtype: "intimation" }, care), "routine");
  assert.equal(tier({ category: "management_change", subtype: "board" }, care), "routine");
  assert.equal(tier({ category: "unclassified", subtype: "esop" }, care), "routine");
});

test("unusual moves use the investor's thresholds", () => {
  const px = Array.from({ length: 25 }, (_, i) => ({ d: `2026-10-${String(i + 1).padStart(2, "0")}`, c: 100, v: 1000 }));
  px.push({ d: "2026-10-26", c: 95, v: 1000 });
  px.push({ d: "2026-10-27", c: 95.5, v: 3000 });
  const m = unusual(px, { movePct: 4, volX: 2 });
  assert.equal(m.length, 2);
  assert.ok(m[0].priceHit && !m[0].volHit && m[0].chg === -5);
  assert.ok(m[1].volHit && !m[1].priceHit);
  assert.equal(unusual(px, { movePct: 6, volX: 4 }).length, 0);
});

test("a filing explains a move only inside the close-to-close window", () => {
  const move = { d: "2026-11-10", prev_d: "2026-11-09" };
  const f = (ts, extra = {}) => ({ ts, category: "press_release", subtype: "news", ...extra });
  assert.equal(explaining(move, [f("2026-11-09T16:00:00+05:30")]).length, 1);   // after previous close
  assert.equal(explaining(move, [f("2026-11-09T15:00:00+05:30")]).length, 0);   // before previous close
  assert.equal(explaining(move, [f("2026-11-10T17:00:00+05:30")]).length, 0);   // after this close
  assert.equal(explaining(move, [f("2026-11-10T10:00:00+05:30", { category: "unclassified" })]).length, 0);
});

test("results absorb their companions; CFO in/out pair up", () => {
  const items = [
    { id: "d", symbol: "K", category: "results", subtype: "deck", ts: "2026-11-10T07:50:00+05:30" },
    { id: "r", symbol: "K", category: "results", subtype: "financials", ts: "2026-11-10T07:40:00+05:30" },
    { id: "a", symbol: "O", category: "management_change", card: { type: "people" }, ts: "2026-11-10T09:06:00+05:30" },
    { id: "b", symbol: "O", category: "management_change", card: { type: "people" }, ts: "2026-11-10T09:05:00+05:30" },
  ];
  const g = group(items);
  assert.deepEqual(g.map((x) => x.id), ["a", "r"]);
  assert.equal(g[1].related[0].id, "d");
  assert.equal(g[0].twins[0].id, "b");
});

test("window start", () => {
  const now = Date.parse("2026-11-10T12:00:00Z");
  assert.equal(windowStart("3d", now).toISOString(), "2026-11-07T12:00:00.000Z");
  assert.equal(windowStart("since", now, { start: "2026-11-09T12:00:00Z" }).toISOString(), "2026-11-09T12:00:00.000Z");
  assert.equal(windowStart("since", now, {}).toISOString(), "2026-11-09T12:00:00.000Z");
});

test("buried summary", () => {
  const k = buriedKinds([{ category: "unclassified" }, { category: "unclassified" }, { category: "agm_egm" },
    { category: "investor_meetings" }, { category: "investor_meetings" }],
    { unclassified: "Routine paperwork", agm_egm: "AGM / EGM", investor_meetings: "Investor meeting" });
  assert.deepEqual(k, ["2 routine paperwork", "2 investor meetings", "1 AGM / EGM"]);
});

test("custom range covers whole India-time days and never runs past now", () => {
  const now = Date.parse("2026-11-10T12:00:00Z"); // 17:30 IST on 10 Nov
  const r = windowRange("custom", now, {}, { from: "2026-11-03", to: "2026-11-05" });
  assert.equal(r.start.toISOString(), "2026-11-02T18:30:00.000Z");
  assert.equal(r.end.toISOString(), "2026-11-05T18:29:59.999Z");
  const swapped = windowRange("custom", now, {}, { from: "2026-11-10", to: "2026-11-08" });
  assert.equal(swapped.from, "2026-11-08");
  assert.equal(swapped.end.getTime(), now);
  const dflt = windowRange("custom", now, {}, {});
  assert.equal(dflt.from, "2026-11-04");
  assert.equal(windowRange("3d", now).end.getTime(), now);
});

import { callQuestions, questionsText, briefScript, spokenName, target } from "../../public/js/logic.js";

const P = (o) => ({ statement: "s", made_in: "Q2 FY26", history: [], specificity: "hard", ...o });

test("questions put contradictions and misses first, cap quiet promises at three", () => {
  const ps = [
    P({ id: "d1", status: "dropped", history: [{ quarter: "Q3 FY26", kind: "reiterated" }, { quarter: "Q4 FY26", kind: "not_mentioned" }, { quarter: "Q1 FY27", kind: "not_mentioned" }] }),
    P({ id: "d2", status: "dropped" }), P({ id: "d3", status: "dropped" }), P({ id: "d4", status: "dropped" }),
    P({ id: "m", status: "missed", target: { low: 27000, unit: "crore" }, horizon: "FY26",
        actual: { value: 19300, unit: "crore", period: "Q3 FY26", source: "management, Q3 FY26 call" } }),
    P({ id: "c", status: "missed", contradiction: true }),
    P({ id: "k", status: "kept" }),
    P({ id: "due", status: "on_track", horizon_end: "Q4 FY27" }),
    P({ id: "far", status: "on_track", horizon_end: "Q4 FY28" }),
  ];
  const qs = callQuestions(ps, "Q2 FY27");
  assert.deepEqual(qs.map((q) => q.id), ["c", "m", "d1", "d2", "d3", "due"]);
  assert.equal(qs[1].facts.join(" | "), "Target: ₹27,000 cr by FY26 | Reported: ₹19,300 cr, per management on the Q3 FY26 call");
  assert.match(qs[2].ask, /not mentioned this for 2 calls/);
  assert.equal(qs[2].facts[0], "Last mentioned on the Q3 FY26 call");
  const text = questionsText("BEL", qs.slice(0, 2));
  assert.match(text, /^Questions for BEL management/);
  assert.match(text, /2\. This was missed/);
});

test("a guidance cut names both numbers, unless one is a misread unit", () => {
  const cut = P({ id: "x", status: "slipping", revised: "worse", target: { low: 1, high: 2, unit: "%" },
                  original_target: { low: 1.5, high: 3.5, unit: "%" }, history: [{ quarter: "Q1 FY27", kind: "lowered" }] });
  assert.match(callQuestions([cut], "Q2 FY27")[0].ask, /^Guidance went from 1\.5–3\.5% to 1–2% on the Q1 FY27 call/);
  const bad = { ...cut, target: { low: 6.7e9, high: 7e9, unit: "crore" }, original_target: { low: 7500, high: 8000, unit: "crore" } };
  assert.match(callQuestions([bad], "Q2 FY27")[0].ask, /^Guidance was softened on the Q1 FY27 call/);
  assert.equal(target({ low: 6.7e9, unit: "crore" }), "");
  assert.equal(target({ low: 27000, unit: "crore" }), "₹27,000 cr");
});

test("brief speaks numbers as words, follows cards and stays short", () => {
  const results = { key: "r", name: "Kaynes Technology India Ltd", card: { type: "results", ok: true, quarter: "Q2 FY27",
    rows: [{ key: "revenue", value: 952.5, yoy: { pct: 4.4 } }, { key: "pat", value: 45.42, yoy: { pct: -61.6 } }],
    promise_check: [{ verdict: "below" }] } };
  const people = { key: "p", name: "Trent Ltd", card: { type: "people", changes: [{ name: "A B", action: "appointed", role: "CFO" }] } };
  const segs = briefScript({ window: "24h", companies: 18, promise: [results],
    moves: [{ key: "m", name: "Bharat Electronics Ltd", chg: -2.1, vx: 3.3 }], material: [people], buried: 4 });
  assert.equal(segs[0].say, "3 things matter in the last 24 hours, across your 18 companies.");
  assert.equal(segs[1].key, "r");
  assert.equal(segs[1].say, "Kaynes Technology reported Q2 FY27 results. Revenue 953 crore rupees, up 4.4 percent on last year. Profit after tax 45.4 crore rupees, down 62 percent. That falls short of what management promised.");
  assert.equal(segs[2].say, "Bharat Electronics fell 2.1 percent on 3.3 times its usual volume, and no filing explains it.");
  assert.equal(segs[3].say, "Trent: a management change. A B is appointed as CFO.");
  assert.equal(segs.at(-1).say, "4 routine filings were buried.");
  assert.ok(segs.every((s) => !/[₹%]/.test(s.say)));
  const many = briefScript({ window: "7d", companies: 18, material: Array.from({ length: 9 }, (_, i) => ({ key: `k${i}`, name: "X Ltd", summary: "A thing happened" })) });
  assert.equal(many.length, 1 + 6 + 1);
  assert.equal(many.at(-1).say, "And 3 more on screen.");
  assert.equal(briefScript({ window: "since", companies: 18 })[0].say, "Nothing needs you since your last visit, across your 18 companies.");
  assert.equal(spokenName("Dixon Technologies (India) Ltd"), "Dixon Technologies");
  const own = briefScript({ window: "24h", companies: 18, material: [{ key: "j", name: "Kaynes Technology India Ltd", summary: "Kaynes Technology approved a JV" }] });
  assert.equal(own[1].say, "Kaynes Technology approved a JV.");
});
