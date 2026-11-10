"""GET /api/company?t=SYMBOL — any NSE company, on demand.

Returns identity, the exchange-derived quarterly table, links to the latest
earnings-call transcripts and annual reports, and 6 months of prices.
No model call: this is the cheap first step of research."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finn.sources import prices, screener  # noqa: E402
from finn.web import ApiError, make_handler, symbol  # noqa: E402

N_CALLS = 5


def get(q):
    sym = symbol(q.get("t"))
    try:
        co = screener.fetch_company(sym)
    except Exception as e:
        if getattr(e, "status", None) == 404:
            raise ApiError(404, f"{sym} was not found. Check the NSE symbol.")
        raise
    try:
        co["prices"] = prices.daily(sym, "6mo")
    except Exception:
        co["prices"] = []
    co["transcripts"] = co["transcripts"][:N_CALLS]
    co["latest_quarter"] = co["quarters"]["periods"][-1] if co["quarters"]["periods"] else None
    return co


handler = make_handler(get=get)
