"""End-of-day prices and volumes from Yahoo Finance's chart endpoint.

Uses the same endpoint the yfinance library uses, without the dependency.
NSE symbols take the .NS suffix; BSE is tried if NSE has no data.
"""
from __future__ import annotations

import datetime as dt

from .. import http

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def daily(symbol: str, range_: str = "6mo") -> list[dict]:
    last = None
    for suffix in (".NS", ".BO"):
        try:
            r = http.get(CHART.format(symbol.upper() + suffix),
                         params={"range": range_, "interval": "1d", "includePrePost": "false"},
                         expect="json")
        except http.FetchError as e:
            last = e
            continue
        res = ((r.json() or {}).get("chart") or {}).get("result") or []
        if not res:
            continue
        res = res[0]
        ts = res.get("timestamp") or []
        q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        out = []
        for i, t in enumerate(ts):
            c = (q.get("close") or [None])[i] if i < len(q.get("close") or []) else None
            v = (q.get("volume") or [None])[i] if i < len(q.get("volume") or []) else None
            if c is None:
                continue
            d = dt.datetime.fromtimestamp(t, IST).date().isoformat()
            out.append({"d": d, "c": round(float(c), 2), "v": int(v or 0)})
        if out:
            return out
    alt = _yfinance(symbol, range_)
    if alt:
        return alt
    if last:
        raise last
    raise http.FetchError(symbol, None, "no price data")


def _yfinance(symbol: str, range_: str) -> list[dict]:
    """Fallback through the yfinance library when it is installed (pipeline only)."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        df = yf.Ticker(symbol.upper() + ".NS").history(period=range_, interval="1d", auto_adjust=False)
    except Exception:
        return []
    return [{"d": idx.date().isoformat(), "c": round(float(r["Close"]), 2), "v": int(r["Volume"] or 0)}
            for idx, r in df.iterrows() if r["Close"] == r["Close"]]
