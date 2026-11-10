"""Turn raw filings into ranked feed items.

Three tiers, decided in this order:
  1. "promise"  — results (the moment promises are tested) and any filing that
                  bears on an open promise in the company's ledger.
  2. "material" — a category the investor cares about, not a routine variant,
                  and not judged low-importance by the reader.
  3. "routine"  — everything else: buried, counted, one tap away.
The browser re-runs the same rules with the investor's own settings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .classify import classify, is_routine

CATS = json.loads((Path(__file__).resolve().parent.parent / "config" / "categories.json").read_text(encoding="utf-8"))
DEFAULT_CARE = {c["id"] for c in CATS["categories"] if c["care"]}

READ_CATEGORIES = {"M&A", "fund_raise", "litigation", "credit_rating", "capex", "press_release",
                   "pledging", "insider_trading", "bonus_split"}


def tier(item: dict, care: Optional[set] = None) -> str:
    care = DEFAULT_CARE if care is None else care
    if item.get("promise_links") or (item["category"] == "results" and item.get("subtype") == "financials"):
        return "promise"
    if item.get("routine") or item["category"] not in care:
        return "routine"
    if item.get("importance") == "low":
        return "routine"
    return "material"


def base_item(raw: dict, name: str) -> dict:
    c = classify(raw)
    return {
        "id": raw["id"], "symbol": raw["symbol"], "name": name, "ts": raw.get("ts"),
        "headline": raw.get("headline") or raw.get("raw_category") or "Filing",
        "exchange_label": " / ".join(x for x in (raw.get("raw_category"), raw.get("raw_subcategory")) if x),
        "category": c["category"], "subtype": c["subtype"], "confidence": c["confidence"],
        "routine": is_routine(c["category"], c["subtype"]),
        "source": raw.get("source"), "attachment": raw.get("attachment"),
        "summary": None, "why": None, "importance": None, "card": None, "promise_links": [],
    }


def needs_reading(item: dict) -> Optional[str]:
    """Which reader (if any) an item deserves. None = headline is enough."""
    if not item.get("attachment"):
        return None
    if item["category"] == "results" and item["subtype"] == "financials":
        return "results"
    if item["category"] == "management_change" and item["subtype"] == "top":
        return "person"
    if item["category"] in READ_CATEGORIES and not item["routine"]:
        return "filing"
    return None


def promise_check(card: dict, promises: list[dict]) -> list[dict]:
    """Compare a results card's numbers with open % promises. Code, not a model."""
    if not card or not card.get("ok"):
        return []
    rows = {r["key"]: r for r in card["rows"]}
    out = []
    for p in promises:
        if p.get("closed") or p.get("basis") == "constant_currency":
            continue
        lo, hi = p["target"].get("low"), p["target"].get("high")
        if lo is None and hi is None:
            continue
        val = None
        if p["metric"] == "revenue_growth":
            val = rows.get("revenue", {}).get("yoy", {}).get("pct")
        elif p["metric"] == "pat_growth":
            val = rows.get("pat", {}).get("yoy", {}).get("pct")
        elif p["metric"] == "ebitda_margin" and not card.get("lender"):
            val = card.get("ebitda_margin")
        if val is None:
            continue
        low = lo if lo is not None else hi
        high = hi if hi is not None else lo
        verdict = "below" if val < low else ("above" if val > high else "within")
        out.append({"promise_id": p["id"], "statement": p["statement"], "metric": p["metric"],
                    "target": {"low": lo, "high": hi}, "value": val, "verdict": verdict,
                    "horizon": p.get("horizon")})
    return out
