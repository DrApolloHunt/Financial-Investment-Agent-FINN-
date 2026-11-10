import test from "node:test";
import assert from "node:assert/strict";
import { tier, unusual, explaining, group, windowStart, buriedKinds } from "../../public/js/logic.js";

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
