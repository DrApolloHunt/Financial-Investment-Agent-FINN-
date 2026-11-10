"""The promise ledger: what management said it would do, call by call, and
whether it happened.

Build order, per company:
  1. Read the last N earnings-call transcripts oldest -> newest (cheap model).
     Each call yields NEW promises and UPDATES to promises already open,
     including silence ("not_mentioned"), which is how quietly dropped
     promises are caught.
  2. Compute delivered numbers from the exchange-derived quarterly table where
     the promise is checkable in rupees (code, no model).
  3. Assign statuses with explicit rules (code), then one reasoning-model call
     writes one-line verdicts and a short credibility read.

State is a plain dict so the on-demand API can run one transcript per request
and the browser can show the ledger filling in.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from . import cache, gemini
from .financials import actual_for, scope_of
from .periods import qkey

V_PROMISES = "l4"
V_VERDICT = "v3"

N = {"type": "NUMBER", "nullable": True}
METRICS = ["revenue_growth", "ebitda_margin", "pat_growth", "volume_growth", "order_inflow",
           "order_book", "capex", "capacity", "debt", "market_share", "launch", "cost", "other"]
KINDS = ["reiterated", "raised", "lowered", "delivered", "missed", "delayed", "withdrawn", "not_mentioned"]
STATUSES = ["kept", "on_track", "pending", "slipping", "missed", "dropped"]

PROMISE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "updates": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "promise_id": {"type": "STRING"},
                "kind": {"type": "STRING", "enum": KINDS},
                "new_target_low": N, "new_target_high": N, "reported_value": N,
                "quote": {"type": "STRING"}, "note": {"type": "STRING"},
            },
            "required": ["promise_id", "kind"]}},
        "new_promises": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "statement": {"type": "STRING"},
                "quote": {"type": "STRING"},
                "speaker": {"type": "STRING"},
                "theme": {"type": "STRING", "enum": ["growth", "margin", "capex", "balance_sheet", "other"]},
                "metric": {"type": "STRING", "enum": METRICS},
                "basis": {"type": "STRING", "enum": ["yoy", "fy", "quarter", "cagr", "absolute", "constant_currency", "other"]},
                "direction": {"type": "STRING", "enum": ["higher_is_better", "lower_is_better"]},
                "target_low": N, "target_high": N,
                "unit": {"type": "STRING"},
                "horizon": {"type": "STRING"},
                "horizon_end": {"type": "STRING", "nullable": True},
                "specificity": {"type": "STRING", "enum": ["hard", "soft"]},
            },
            "required": ["statement", "quote", "theme", "metric", "horizon", "specificity"]}},
    },
    "required": ["updates", "new_promises"],
}

PROMISE_PROMPT = """You are keeping a ledger of what management PROMISED, using one earnings-call transcript of {name} ({symbol}) for {quarter}.

A promise is a forward-looking commitment management makes about the business, ideally with a number or a date:
revenue or volume growth, a margin range, capex amount, capacity coming on stream by a date, order inflow,
debt targets, launches, market share. NOT promises: macro views, vague optimism, analyst questions,
past results, or topics management declines to guide on.

Open promises from earlier calls:
{prior}

A) updates: for EVERY open promise above, say what this call does to it:
   reiterated | raised | lowered | delivered (management says achieved) | missed (management says not achieved)
   | delayed (timeline pushed) | withdrawn (explicitly dropped) | not_mentioned.
   Give the new target if it changed, any value management reports as achieved, and a verbatim quote (≤25 words) when mentioned.
B) new_promises: up to {max_new} NEW promises from this call that are not restatements of the open ones.
   Prefer specific, checkable ones. statement: plain English, ≤20 words. quote: verbatim, ≤25 words.
   horizon: as stated (e.g. "FY26", "Q3 FY26", "next 2-3 years"). horizon_end: the fiscal quarter by which it can be
   judged, formatted like "Q4 FY26" (Indian fiscal year Apr–Mar), or null if open-ended.
   basis: constant_currency if guidance is in constant currency; fy for full-year targets.

Use only this transcript. Do not use outside knowledge of the company."""


# ---- state ---------------------------------------------------------------

def new_state(symbol: str, name: str) -> dict:
    return {"symbol": symbol.upper(), "name": name, "calls": [], "promises": []}


def open_promises(state: dict) -> list[dict]:
    return [p for p in state["promises"] if not p.get("closed")]


def _norm_horizon_end(p: dict) -> Optional[str]:
    he = (p.get("horizon_end") or "").upper().replace("  ", " ").strip()
    if re.fullmatch(r"Q[1-4] FY\d{2}", he):
        return he
    h = (p.get("horizon") or "").upper()
    m = re.search(r"Q([1-4])\s*FY\s*'?(\d{2,4})", h)
    if m:
        return f"Q{m.group(1)} FY{int(m.group(2)) % 100:02d}"
    m = re.search(r"H([12])\s*FY\s*'?(\d{2,4})", h)
    if m:
        return f"Q{2 if m.group(1) == '1' else 4} FY{int(m.group(2)) % 100:02d}"
    m = re.search(r"FY\s*'?(\d{2,4})", h)
    if m:
        return f"Q4 FY{int(m.group(1)) % 100:02d}"
    return None


def _promise_key(quarter: str) -> str:
    fy, q = qkey(quarter)
    return f"{fy:02d}Q{q}"


def apply_call(state: dict, quarter: str, url: str, result: dict, model: str = "") -> dict:
    """Merge one transcript's extraction into the state (pure, deterministic)."""
    if any(c["quarter"] == quarter for c in state["calls"]):
        return state
    state["calls"].append({"quarter": quarter, "url": url, "model": model})
    by_id = {p["id"]: p for p in open_promises(state)}
    seen = set()
    for u in result.get("updates") or []:
        p = by_id.get(u.get("promise_id"))
        if not p or u.get("kind") not in KINDS:
            continue
        seen.add(p["id"])
        ev = {"quarter": quarter, "kind": u["kind"], "quote": (u.get("quote") or "")[:220],
              "note": (u.get("note") or "")[:160], "url": url}
        if u["kind"] in ("raised", "lowered"):
            ev["target"] = {"low": u.get("new_target_low"), "high": u.get("new_target_high")}
            if ev["target"]["low"] is not None or ev["target"]["high"] is not None:
                p["target"] = {**p["target"], **{k: v for k, v in ev["target"].items() if v is not None}}
        if u.get("reported_value") is not None:
            ev["reported"] = u["reported_value"]
        p["history"].append(ev)
        if u["kind"] in ("delivered", "missed", "withdrawn"):
            p["closed"] = True
    for p in by_id.values():
        if p["id"] not in seen:
            p["history"].append({"quarter": quarter, "kind": "not_mentioned", "url": url})
    base = _promise_key(quarter)
    for i, n in enumerate((result.get("new_promises") or [])[:8], 1):
        p = {
            "id": f"{state['symbol']}-{base}-{i}",
            "statement": (n.get("statement") or "").strip()[:200],
            "quote": (n.get("quote") or "").strip()[:240],
            "speaker": (n.get("speaker") or "").strip()[:80],
            "theme": n.get("theme") or "other",
            "metric": n.get("metric") if n.get("metric") in METRICS else "other",
            "basis": n.get("basis") or "other",
            "direction": n.get("direction") or "higher_is_better",
            "target": {"low": n.get("target_low"), "high": n.get("target_high"), "unit": n.get("unit") or ""},
            "horizon": (n.get("horizon") or "").strip()[:60],
            "specificity": n.get("specificity") or "soft",
            "made_in": quarter, "source_url": url, "history": [],
        }
        p["original_target"] = dict(p["target"])
        p["horizon_end"] = _norm_horizon_end({**n, **p})
        if p["statement"]:
            state["promises"].append(p)
    return state


def read_call(state: dict, quarter: str, url: str, pdf_bytes_fn) -> dict:
    """Extract one call (cached) and merge it."""
    prior = [{"id": p["id"], "statement": p["statement"], "target": p["target"], "horizon": p["horizon"]}
             for p in open_promises(state)]
    ident = url + "|" + hashlib.sha1(json.dumps(prior, sort_keys=True).encode()).hexdigest()[:10]
    key = cache.key_for("promises", ident, V_PROMISES)
    hit = cache.get(key)
    if hit is None:
        prior_txt = "\n".join(f"{p['id']}: {p['statement']} (horizon {p['horizon']})" for p in prior) or "(none yet)"
        prompt = PROMISE_PROMPT.format(name=state["name"], symbol=state["symbol"], quarter=quarter,
                                       prior=prior_txt, max_new=8 if not prior else 6)
        data, model = gemini.generate_json("promises", [gemini.pdf_part(pdf_bytes_fn(url)), {"text": prompt}],
                                           PROMISE_SCHEMA)
        hit = {"result": data, "model": model}
        cache.put(key, hit)
    return apply_call(state, quarter, url, hit["result"], hit.get("model", ""))


# ---- status rules ---------------------------------------------------------

def _meets(value: float, target: dict, direction: str) -> Optional[bool]:
    lo, hi = target.get("low"), target.get("high")
    if direction == "lower_is_better":
        bound = hi if hi is not None else lo
        return None if bound is None else value <= bound
    bound = lo if lo is not None else hi
    return None if bound is None else value >= bound


def _silent_streak(history: list[dict]) -> int:
    n = 0
    for ev in reversed(history):
        if ev["kind"] == "not_mentioned":
            n += 1
        else:
            break
    return n


def assess(p: dict, quarters: dict, latest: Optional[str]) -> dict:
    """Status for one promise. Returns the promise with actual/status/reason."""
    hist = p.get("history") or []
    explicit = [e for e in hist if e["kind"] not in ("reiterated", "not_mentioned")]
    last = explicit[-1] if explicit else None
    reported = next((e for e in reversed(hist) if e.get("reported") is not None), None)

    unit = (p["target"].get("unit") or "").strip()
    actual = None
    if p["metric"] in ("revenue_growth", "pat_growth", "ebitda_margin") and unit in ("", "%"):
        actual = actual_for(p["metric"], p.get("basis") or "", p.get("horizon_end"), quarters, latest,
                            scope=scope_of(p.get("horizon") or ""))
        if actual:
            actual["source"] = "exchange data"
    if actual is None and reported is not None:
        actual = {"value": reported["reported"], "unit": unit, "period": reported["quarter"],
                  "ytd": False, "source": "management, " + reported["quarter"] + " call",
                  "note": reported.get("note") or ""}

    due = bool(p.get("horizon_end") and latest and qkey(latest) >= qkey(p["horizon_end"]))
    status, reason = "pending", "Not yet due."
    lower_better = p.get("direction") == "lower_is_better"
    table_says = None
    if due and actual is not None and actual.get("source") == "exchange data" and not actual.get("ytd"):
        table_says = _meets(actual["value"], p["target"], p.get("direction", ""))
    contradiction = False

    if last and last["kind"] == "withdrawn":
        status, reason = "dropped", f"Withdrawn on the {last['quarter']} call."
    elif last and last["kind"] == "missed":
        status, reason = "missed", f"Management said it was missed ({last['quarter']})."
    elif last and last["kind"] == "delivered" and table_says is False:
        status, contradiction = "missed", True
        reason = (f"Management called it delivered ({last['quarter']}); exchange data shows "
                  f"{actual['value']}{actual['unit']} for {actual['period']}.")
    elif last and last["kind"] == "delivered":
        status, reason = "kept", f"Management reported it delivered ({last['quarter']})."
    elif table_says is not None:
        status = "kept" if table_says else "missed"
        reason = f"{actual['period']}: {actual['value']}{actual['unit']} vs target."
    elif due and actual is not None and (m := _meets(actual["value"], p["target"], p.get("direction", ""))) is not None and not actual.get("ytd"):
        status = "kept" if m else "missed"
        reason = f"{actual['period']}: {actual['value']}{actual['unit']} vs target."
    elif _silent_streak(hist) >= 2:
        status, reason = "dropped", f"Not mentioned on the last {_silent_streak(hist)} calls."
    elif due and not hist:
        status, reason = "pending", "Due; no later call read yet."
    elif due:
        status, reason = "slipping", "Due, but no confirmation it was delivered."
    elif last and (last["kind"] == "delayed"
                   or (last["kind"] == "lowered" and not lower_better)
                   or (last["kind"] == "raised" and lower_better)):
        word = {"delayed": "Pushed out", "lowered": "Guidance cut", "raised": "Guidance worsened"}[last["kind"]]
        status, reason = "slipping", f"{word} on the {last['quarter']} call."
    elif actual is not None and (m := _meets(actual["value"], p["target"], p.get("direction", ""))) is not None:
        status = "on_track" if m else "slipping"
        reason = f"{actual['period']}: {actual['value']}{actual['unit']}."
    elif last and last["kind"] in ("raised", "lowered"):
        status, reason = "on_track", f"Target improved on the {last['quarter']} call."
    elif any(e["kind"] == "reiterated" for e in hist):
        status, reason = "on_track", "Reiterated since."

    revised = None
    for e in hist:
        if e["kind"] in ("raised", "lowered"):
            better = (e["kind"] == "raised") != lower_better
            revised = "better" if better else "worse"
    if revised == "worse" and status in ("kept", "on_track"):
        o = p.get("original_target") or {}
        orig = _fmt_target(o)
        if orig:
            reason += f" Only after cutting the target (originally {orig})."
    return {**p, "actual": actual, "status": status, "reason": reason, "revised": revised,
            "contradiction": contradiction, "closed": status in ("kept", "missed", "dropped")}


VERDICT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "credibility": {"type": "STRING", "description": "≤45 words: how reliably this management team delivers on what it says"},
        "lines": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"id": {"type": "STRING"}, "line": {"type": "STRING", "description": "≤16 words"}},
            "required": ["id", "line"]}},
        "overrides": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"id": {"type": "STRING"},
                           "status": {"type": "STRING", "enum": STATUSES},
                           "reason": {"type": "STRING"}},
            "required": ["id", "status", "reason"]}},
    },
    "required": ["credibility", "lines", "overrides"],
}

VERDICT_PROMPT = """You are an analyst judging management's promise-keeping for {name}, using ONLY the ledger below
(built from their own earnings calls and exchange-reported numbers). No outside knowledge.

For each promise write one plain line (≤16 words) on promised vs delivered, with numbers where present.
Only override a status if the evidence in the ledger clearly contradicts it; give the reason.
Then a credibility read (≤45 words): do they hit what they guide, revise quietly, or drop topics?

Ledger:
{ledger}"""


def _fmt_target(t: dict) -> str:
    lo, hi, u = t.get("low"), t.get("high"), t.get("unit") or ""
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None and lo != hi:
        return f"{lo:g}–{hi:g}{u}"
    return f"{(lo if lo is not None else hi):g}{u}"


def _template_line(p: dict) -> str:
    t = p["target"]
    tgt = ""
    if t.get("low") is not None or t.get("high") is not None:
        lo, hi = t.get("low"), t.get("high")
        tgt = f"{lo}–{hi}{t.get('unit','')}" if lo is not None and hi is not None and lo != hi else f"{lo if lo is not None else hi}{t.get('unit','')}"
    a = p.get("actual")
    if a:
        return f"Target {tgt or p['horizon']}; {a['period']}: {a['value']}{a['unit']}."
    return p["reason"]


def finalize(state: dict, quarters: dict, latest: Optional[str], use_model: bool = True) -> dict:
    promises = [assess(p, quarters, latest) for p in state["promises"]]
    credibility, model = None, None
    if use_model and promises:
        compact = [{"id": p["id"], "said": p["statement"], "made_in": p["made_in"], "target": p["target"],
                    "horizon": p["horizon"], "history": [f"{e['quarter']}:{e['kind']}" + (f"({e.get('reported')})" if e.get("reported") is not None else "") for e in p["history"]],
                    "actual": p["actual"] and {k: p["actual"][k] for k in ("value", "unit", "period", "source")},
                    "status": p["status"]} for p in promises]
        blob = json.dumps(compact, ensure_ascii=False)
        key = cache.key_for("verdict", hashlib.sha1(blob.encode()).hexdigest(), V_VERDICT)
        hit = cache.get(key)
        if hit is None:
            try:
                data, model = gemini.generate_json("verdict", [{"text": VERDICT_PROMPT.format(name=state["name"], ledger=blob)}],
                                                   VERDICT_SCHEMA, temperature=0.2)
                hit = {"data": data, "model": model}
                cache.put(key, hit)
            except gemini.GeminiError:
                hit = None
        if hit:
            data, model = hit["data"], hit.get("model")
            lines = {d["id"]: d["line"] for d in data.get("lines", [])}
            over = {d["id"]: d for d in data.get("overrides", []) if d.get("status") in STATUSES}
            for p in promises:
                if p["id"] in lines:
                    p["verdict"] = lines[p["id"]][:160]
                if p["id"] in over:
                    p["status_rule"] = p["status"]
                    p["status"] = over[p["id"]]["status"]
                    p["reason"] = over[p["id"]]["reason"][:200]
            credibility = (data.get("credibility") or "")[:400]
    for p in promises:
        p.setdefault("verdict", _template_line(p))
    order = {s: i for i, s in enumerate(["missed", "slipping", "dropped", "on_track", "pending", "kept"])}
    promises.sort(key=lambda p: (order.get(p["status"], 9), -qkey(p["made_in"])[0], -qkey(p["made_in"])[1]))
    counts = {s: sum(1 for p in promises if p["status"] == s) for s in STATUSES}
    return {**state, "promises": promises, "counts": counts, "credibility": credibility,
            "verdict_model": model, "latest_quarter": latest}
