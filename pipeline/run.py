"""FINN data pipeline. Writes static JSON to public/data for the app.

Modes:
  full      companies (screener), prices, ledgers, 30 days of filings
  intraday  filings from the last 3 days only (hourly during market hours)
  eod       prices + intraday (after the close)

Usage:
  python -m pipeline.run --mode full [--only INFY,TCS] [--days 30] [--no-ai]

Every model call is cached in public/data/cache, so a re-run only pays for
documents it has never read. A per-run budget caps model reads of filings.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finn import business, fundamentals, gemini, ledger, moves, readers, triage  # noqa: E402
from finn import alerts  # noqa: E402
from finn.classify import classify_batch_with_model, is_routine  # noqa: E402
from finn.financials import complete_from_table, cross_check, results_card  # noqa: E402
from finn.http import FetchError  # noqa: E402
from finn.sources import exchanges, prices, screener  # noqa: E402

DATA = Path(os.environ.get("FINN_DATA_DIR") or ROOT / "public" / "data")
CONFIG = json.loads(Path(os.environ.get("FINN_CONFIG") or ROOT / "config" / "portfolio.json").read_text(encoding="utf-8"))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# A run stops starting new model reads once its time budget is spent, then writes
# everything it has. Every read is cached, so the next run continues from there.
DEADLINE = time.time() + 60 * float(os.environ.get("FINN_TIME_BUDGET_MIN", "35"))


def time_left() -> bool:
    return time.time() < DEADLINE


# Web-searched backgrounds for appointees whose filing has no profile: a few per full run.
# Quick runs skip them: on the free tier each refused lookup costs about two minutes.
WEB_BIO_CAP = int(os.environ.get("FINN_WEB_BIO_CAP", "8"))
WEB_BIO_ON = [True]


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# ---- companies + ledgers ------------------------------------------------------

def build_company(sym: str, sector: str, use_ai: bool, n_calls: int, status: dict) -> dict:
    path = DATA / "companies" / f"{sym}.json"
    old = load(path, {})
    t0 = time.time()
    try:
        co = screener.fetch_company(sym)
        status["screener_ok"] += 1
        log(f"  {sym} screener: {len(co['quarters']['periods'])} quarters, {len(co['transcripts'])} transcripts ({time.time()-t0:.0f}s)")
    except Exception as e:  # keep yesterday's data rather than blanking the company
        status["errors"].append(f"{sym} screener: {e}")
        if old:
            return old
        co = {"symbol": sym, "name": sym, "quarters": {"periods": [], "rows": {}}, "transcripts": [],
              "annual_reports": [], "bse_code": None, "basis": None}
    co["sector"] = sector
    co["fundamentals"] = fundamentals.summarize(co)
    t0 = time.time()
    try:
        co["prices"] = prices.daily(sym, "6mo")
        status["prices_ok"] += 1
        log(f"  {sym} prices: {len(co['prices'])} days ({time.time()-t0:.0f}s)")
    except Exception as e:
        status["errors"].append(f"{sym} prices: {e}")
        log(f"  {sym} prices failed ({time.time()-t0:.0f}s): {str(e)[:120]}")
        co["prices"] = old.get("prices", [])

    co["business"] = old.get("business")
    ar = business.latest_report(co.get("annual_reports") or [])
    if use_ai and ar and time_left():
        t0 = time.time()
        try:
            co["business"] = business.read_business(co["name"], ar["url"], ar.get("label", "")) or co["business"]
            log(f"  {sym} business snapshot: {len((co['business'] or {}).get('segments') or [])} segments ({time.time()-t0:.0f}s)")
        except Exception as e:
            status["errors"].append(f"{sym} annual report: {str(e)[:160]}")
            log(f"  {sym} annual report failed ({time.time()-t0:.0f}s): {str(e)[:120]}")

    latest = co["quarters"]["periods"][-1] if co["quarters"]["periods"] else None
    calls = list(reversed(co["transcripts"][:n_calls]))  # oldest -> newest
    state = ledger.new_state(sym, co["name"])
    if use_ai and calls and not time_left() and old.get("ledger"):
        co["ledger"] = old["ledger"]          # out of time: keep yesterday's ledger
    elif use_ai and calls:
        for c in calls:
            if not time_left():
                status["errors"].append(f"{sym}: time budget spent before {c['quarter']} call; continues next run")
                break
            try:
                state = ledger.read_call(state, c["quarter"], c["url"], exchanges.download_attachment)
                log(f"  {sym} {c['quarter']}: {len(state['promises'])} promises so far")
            except Exception as e:
                status["errors"].append(f"{sym} transcript {c['quarter']}: {e}")
                log(f"  {sym} {c['quarter']} transcript failed: {e}")
        t0 = time.time()
        co["ledger"] = ledger.finalize(state, co["quarters"], latest, use_model=True,
                                       context=ledger.context_for(co))
        log(f"  {sym} verdicts: {co['ledger'].get('verdict_model') or 'rules only'} ({time.time()-t0:.0f}s)")
    elif use_ai and (co.get("fundamentals", {}).get("trajectory") or co.get("business")):
        # no earnings calls to hold management to, but the figures still support a bull and bear case
        t0 = time.time()
        co["ledger"] = ledger.finalize(state, co["quarters"], latest, use_model=True,
                                       context=ledger.context_for(co))
        log(f"  {sym} bull/bear from figures only: {co['ledger'].get('verdict_model') or 'none'} ({time.time()-t0:.0f}s)")
    elif old.get("ledger"):
        co["ledger"] = old["ledger"]
    else:
        co["ledger"] = ledger.finalize(state, co["quarters"], latest, use_model=False)
    co["updated_at"] = dt.datetime.now(IST).isoformat(timespec="seconds")
    save(path, co)
    return co


# ---- filings feed ---------------------------------------------------------------

def refresh_feed(companies: dict, days: int, use_ai: bool, budget: int, status: dict) -> list[dict]:
    feed_path = DATA / "feed.json"
    existing = {it["id"]: it for it in load(feed_path, {"items": []})["items"]}
    end = dt.datetime.now(IST).date()
    start = end - dt.timedelta(days=days)
    fresh: list[dict] = []
    for sym, co in companies.items():
        if co.get("research_only"):
            continue
        try:
            raw, src = exchanges.announcements(sym, co.get("bse_code"), start, end)
            status["announcements_ok"] += 1
            status["sources"][src] = status["sources"].get(src, 0) + 1
        except Exception as e:
            status["errors"].append(f"{sym} announcements: {e}")
            continue
        for r in raw:
            if r["id"] in existing:
                continue
            it = triage.base_item(r, co.get("name", sym))
            fresh.append(it)
        time.sleep(0.6)  # be polite to the exchanges
    log(f"filings: {len(fresh)} new, {len(existing)} known")

    # model fallback for the few the rules cannot place: one batched call
    unplaced = [it for it in fresh if it["confidence"] == "low"]
    if use_ai and unplaced:
        try:
            got = classify_batch_with_model([{"id": it["id"], "headline": it["headline"],
                                              "raw_category": it["exchange_label"]} for it in unplaced])
            for it in unplaced:
                if it["id"] in got:
                    it["category"], it["confidence"] = got[it["id"]], "model"
                    it["routine"] = is_routine(it["category"], it["subtype"])
        except gemini.GeminiError as e:
            status["errors"].append(f"classify batch: {e}")

    items = list(existing.values()) + fresh
    cutoff = (dt.datetime.now(IST) - dt.timedelta(days=max(days, 30))).isoformat()
    items = [it for it in items if (it.get("ts") or "") >= cutoff]

    # read the filings that deserve it, most important first, within budget
    def prio(it):
        kind = triage.needs_reading(it)
        rank = {"results": 0, "person": 1, "filing": 2}.get(kind, 9)
        return (rank, -(dt.datetime.fromisoformat(it["ts"]).timestamp() if it.get("ts") else 0))

    def patched(card):
        """How much of a results card came from the exchange table rather than the filing."""
        return 99 if card.get("source") == "table" or not card.get("ok") else len(card.get("filled_from_table") or [])

    def reread(it):
        c = it.get("card") or {}
        return (c.get("type") == "results" and (c.get("filled_from_table") or c.get("source") == "table" or not c.get("ok"))
                and it.get("results_v") != readers.V_RESULTS)

    todo = [it for it in items if triage.needs_reading(it) and (not it.get("read") or reread(it))
            and it.get("attempts", 0) < 2]
    todo.sort(key=prio)
    used = 0
    web_bios = [0]

    def lookup(c, company):
        """Web background for an appointee whose filing has no profile. Small, capped, never fatal."""
        if (not WEB_BIO_ON[0] or c.get("action") not in ("appointed", "redesignated") or (c.get("background") or "").strip()
                or c.get("web_background") or not c.get("name") or web_bios[0] >= WEB_BIO_CAP):
            return
        web_bios[0] += 1
        wb = readers.web_bio(c["name"], c.get("role", ""), company, c.get("action", "appointed"), c.get("effective") or "")
        if wb:
            c["web_background"] = wb
        log(f"  web background {c['name']} ({company}): {'found, ' + str(len(wb['sources'])) + ' sources' if wb else readers.web_bio_error()}")

    # people cards read on earlier runs, before web backgrounds existed
    if use_ai:
        for it in items:
            if (it.get("card") or {}).get("type") == "people":
                for c in it["card"].get("changes", []):
                    lookup(c, it["name"])
    for it in todo:
        if not use_ai or used >= budget or not time_left():
            break
        kind = triage.needs_reading(it)
        co = companies.get(it["symbol"], {})
        # filings may bear on any promise not already settled, including quietly dropped ones
        open_p = [p for p in (co.get("ledger") or {}).get("promises", []) if p.get("status") not in ("kept", "missed")]
        try:
            if kind == "results":
                prev = it.get("card") if (it.get("card") or {}).get("type") == "results" else None
                ext = readers.read_results(it["attachment"])
                it["results_v"] = readers.V_RESULTS
                if prev and not ext.get("is_results_document"):
                    pass                      # a re-read that fails keeps the card already checked
                elif ext.get("is_results_document"):
                    card = results_card(ext)
                    card["cross_check"] = cross_check(card, co.get("quarters") or {})
                    card = complete_from_table(card, co.get("quarters") or {}, bool(co.get("is_lender")))
                    card["promise_check"] = triage.promise_check(card, open_p)
                    if prev:
                        log(f"  re-read {it['symbol']} results: filled from table {prev.get('filled_from_table') or prev.get('source')}"
                            f" -> {card.get('filled_from_table') or card.get('source') or 'none'}")
                    if prev and patched(card) > patched(prev):
                        pass                  # the earlier read needed less help from the exchange table: keep it
                    else:
                        it["card"] = {"type": "results", **card}
                else:
                    it["subtype"], it["routine"] = "other", True
                it["model"] = ext.get("_model")
            elif kind == "person":
                ppl = readers.read_person(it["attachment"])
                changes = ppl.get("changes", [])
                for c in changes:
                    lookup(c, it["name"])
                it["card"] = {"type": "people", "changes": changes}
                if ppl.get("changes") and all(c.get("level") != "top" for c in ppl["changes"]):
                    it["subtype"], it["routine"] = "board", True
                it["model"] = ppl.get("_model")
            else:
                r = readers.read_filing(it["attachment"], it["name"], it["exchange_label"], it["headline"], open_p)
                it.update({"summary": r.get("one_line"), "why": r.get("why"), "importance": r.get("importance"),
                           "model": r.get("_model")})
                stmts = {p["id"]: p["statement"] for p in open_p}
                it["promise_links"] = [{**l, "statement": stmts.get(l["promise_id"], "")} for l in r.get("promise_links", [])]
            it["read"] = True
            used += 1
        except gemini.NoKey:
            status["errors"].append("GEMINI_API_KEY not set: filings not read")
            break
        except (gemini.GeminiError, FetchError) as e:
            status["errors"].append(f"read {it['symbol']} {it['id']}: {str(e)[:160]}")
            it["read_error"] = str(e)[:160]
            it["attempts"] = it.get("attempts", 0) + 1
            used += 1
    log(f"read {used} filings with the model (budget {budget}); {max(0, len(todo) - used)} left for next run")
    log(f"web backgrounds looked up: {web_bios[0]}")


    for it in items:
        it["tier"] = triage.tier(it)
    items.sort(key=lambda it: it.get("ts") or "", reverse=True)
    save(feed_path, {"generated_at": dt.datetime.now(IST).isoformat(timespec="seconds"), "items": items})
    return items


def attach_evidence(items: list[dict], companies: dict) -> None:
    """Show, on each promise, the latest filings that bear on it."""
    touched = set()
    for it in items:
        links = list(it.get("promise_links") or [])
        card = it.get("card") or {}
        for pc in card.get("promise_check") or []:
            links.append({"promise_id": pc["promise_id"], "effect": {"below": "undermines", "within": "supports", "above": "supports"}[pc["verdict"]],
                          "note": f"{card.get('quarter')}: {pc['value']}% this quarter"})
        if not links:
            continue
        co = companies.get(it["symbol"]) or {}
        by_id = {p["id"]: p for p in (co.get("ledger") or {}).get("promises", [])}
        for l in links:
            p = by_id.get(l["promise_id"])
            if not p:
                continue
            ev = p.setdefault("evidence", [])
            if any(e["item_id"] == it["id"] for e in ev):
                continue
            ev.append({"item_id": it["id"], "ts": it.get("ts"), "headline": it.get("summary") or it["headline"],
                       "effect": l["effect"], "note": l.get("note", ""), "attachment": it.get("attachment")})
            ev.sort(key=lambda e: e.get("ts") or "", reverse=True)
            del ev[5:]
            touched.add(it["symbol"])
    for sym in touched:
        save(DATA / "companies" / f"{sym}.json", companies[sym])


# ---- filter stats (the cheap half of the validation test) --------------------

def filter_stats(items: list[dict], companies: dict, days: int = 30) -> dict:
    d = CONFIG["defaults"]
    by_day: dict[str, int] = {}
    for it in items:
        if it.get("ts"):
            day = it["ts"][:10]
            by_day[day] = by_day.get(day, 0) + 1
    tiers = {t: sum(1 for it in items if it.get("tier") == t) for t in ("promise", "material", "routine")}
    unexplained = explained = 0
    for sym, co in companies.items():
        if co.get("research_only"):
            continue
        fl = [it for it in items if it["symbol"] == sym]
        for m in moves.unusual(co.get("prices") or [], d["price_move_pct"], d["volume_multiple"],
                               d["volume_lookback_days"], last_n=days):
            if moves.pair(m, fl):
                explained += 1
            else:
                unexplained += 1
    total = sum(tiers.values()) or 1
    return {
        "window_days": days, "filings": sum(tiers.values()), "by_tier": tiers,
        "buried_pct": round(tiers["routine"] / total * 100, 1),
        "median_filings_per_day": statistics.median(by_day.values()) if by_day else 0,
        "unusual_moves": explained + unexplained, "unexplained_moves": unexplained,
    }


# ---- main ------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "intraday", "eod"], default="full")
    ap.add_argument("--only", default="")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--budget", type=int, default=int(os.environ.get("FINN_LLM_BUDGET", "120")))
    a = ap.parse_args(argv)

    use_ai = not a.no_ai and bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not use_ai:
        log("no GEMINI_API_KEY (or --no-ai): running without model reads")
    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}
    port = [c for c in CONFIG["portfolio"] if not only or c["symbol"] in only]
    research = [s for s in CONFIG["research_demo"] if not only or s in only]
    n_calls = CONFIG["defaults"]["transcripts_per_ledger"]
    status = {"errors": [], "screener_ok": 0, "prices_ok": 0, "announcements_ok": 0, "sources": {}}
    t0 = time.time()

    companies: dict[str, dict] = {}
    WEB_BIO_ON[0] = a.mode == "full"
    if a.mode == "full":
        for c in port:
            log(f"company {c['symbol']}")
            companies[c["symbol"]] = build_company(c["symbol"], c["sector"], use_ai, n_calls, status)
        for s in research:
            log(f"research {s}")
            co = build_company(s, "", use_ai, n_calls, status)
            co["research_only"] = True
            save(DATA / "companies" / f"{s}.json", co)
            companies[s] = co
    else:
        for c in port:
            co = load(DATA / "companies" / f"{c['symbol']}.json", None)
            if co is None:
                co = build_company(c["symbol"], c["sector"], use_ai, n_calls, status)
            elif a.mode == "eod":
                try:
                    co["prices"] = prices.daily(c["symbol"], "6mo")
                    status["prices_ok"] += 1
                    save(DATA / "companies" / f"{c['symbol']}.json", co)
                except Exception as e:
                    status["errors"].append(f"{c['symbol']} prices: {e}")
            companies[c["symbol"]] = co
        for s in CONFIG["research_demo"]:
            co = load(DATA / "companies" / f"{s}.json", None)
            if co:
                companies[s] = {**co, "research_only": True}

    days = a.days or (30 if a.mode == "full" else 3)
    items = refresh_feed(companies, days, use_ai, a.budget, status)

    attach_evidence(items, companies)

    portfolio = []
    for c in CONFIG["portfolio"]:
        co = companies.get(c["symbol"]) or load(DATA / "companies" / f"{c['symbol']}.json", {})
        if not co:
            continue
        lg = co.get("ledger") or {}
        px = co.get("prices") or []
        portfolio.append({
            "symbol": c["symbol"], "name": co.get("name", c["symbol"]), "sector": c["sector"],
            "close": px[-1]["c"] if px else None,
            "chg": round((px[-1]["c"] / px[-2]["c"] - 1) * 100, 2) if len(px) > 1 and px[-2]["c"] else None,
            "spark": [p["c"] for p in px[-60:]],
            "recent": px[-40:],
            "counts": lg.get("counts", {}), "promises": len(lg.get("promises", [])),
            "latest_quarter": lg.get("latest_quarter"), "credibility": lg.get("credibility"),
        })
    save(DATA / "portfolio.json", {"companies": portfolio,
                                   "research": [s for s in CONFIG["research_demo"] if (DATA / "companies" / f"{s}.json").exists()]})

    meta = load(DATA / "meta.json", {})
    usage = gemini.METER.as_dict()
    hist = meta.get("usage_history", [])[-60:]
    hist.append({"at": dt.datetime.now(IST).isoformat(timespec="seconds"), "mode": a.mode, **usage})
    meta.update({
        "generated_at": dt.datetime.now(IST).isoformat(timespec="seconds"),
        "mode": a.mode, "seconds": round(time.time() - t0, 1), "snapshot": False,
        "status": {k: v for k, v in status.items() if k != "errors"},
        "errors": status["errors"][-40:],
        "usage_last_run": usage, "usage_history": hist,
        "routes": {k: gemini.route(k) for k in gemini.ROUTES},
        "filter_stats": filter_stats(items, companies),
        "defaults": CONFIG["defaults"],
    })
    save(DATA / "meta.json", meta)
    if os.environ.get("FINN_ALERTS") == "1":      # set by the scheduled workflow only
        alerts.run(items, companies, CONFIG, DATA, log=log)
    log(f"done in {meta['seconds']}s; model calls {usage['calls']}; errors {len(status['errors'])}")
    for e in status["errors"][:15]:
        log("  !", e)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
