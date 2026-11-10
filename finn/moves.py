"""Unusual end-of-day moves, and whether a filing explains them.

A move on trading day D is close(D) vs close(D-1). A filing can explain it if
it was disseminated after the previous session closed (15:30 IST on D-1) and
before the close on D. A move with no such filing is surfaced as
"unexplained": the price knows something the filings don't say.
(The browser runs the same rules with the investor's own thresholds.)
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CLOSE = dt.time(15, 30)


def unusual(prices: list[dict], move_pct: float = 4.0, vol_mult: float = 2.0,
            lookback: int = 20, last_n: Optional[int] = None) -> list[dict]:
    out = []
    rng = range(1, len(prices))
    if last_n:
        rng = range(max(1, len(prices) - last_n), len(prices))
    for i in rng:
        prev, cur = prices[i - 1], prices[i]
        if not prev.get("c"):
            continue
        chg = (cur["c"] / prev["c"] - 1) * 100
        window = [p["v"] for p in prices[max(0, i - lookback):i] if p.get("v")]
        avg = sum(window) / len(window) if window else 0
        vm = cur["v"] / avg if avg else 0
        price_hit = abs(chg) >= move_pct
        vol_hit = vm >= vol_mult
        if price_hit or vol_hit:
            out.append({"d": cur["d"], "prev_d": prev["d"], "chg": round(chg, 2), "vol_x": round(vm, 2),
                        "price_hit": price_hit, "vol_hit": vol_hit})
    return out


def _window(m: dict):
    start = dt.datetime.combine(dt.date.fromisoformat(m["prev_d"]), CLOSE, IST)
    end = dt.datetime.combine(dt.date.fromisoformat(m["d"]), CLOSE, IST)
    return start, end


def pair(move: dict, filings: list[dict], include_routine: bool = False) -> list[dict]:
    start, end = _window(move)
    hits = []
    for f in filings:
        if not f.get("ts"):
            continue
        t = dt.datetime.fromisoformat(f["ts"])
        if start < t <= end and (include_routine or not f.get("routine")) and f["category"] != "unclassified":
            hits.append(f)
    return hits
