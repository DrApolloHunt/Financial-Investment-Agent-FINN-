"""Deterministic financial arithmetic. Models extract numbers; code does maths.

- Results card: Revenue, EBITDA, PBT, PAT for this quarter vs last quarter
  (QoQ) and vs the same quarter a year ago (YoY), in ₹ crore.
- Quarterly-table helpers for the ledger's "delivered" side.
"""
from __future__ import annotations

from typing import Optional

from .periods import prev_quarter, qkey, year_ago

UNIT_TO_CRORE = {"crore": 1.0, "crores": 1.0, "cr": 1.0, "lakh": 0.01, "lakhs": 0.01,
                 "million": 0.1, "millions": 0.1, "billion": 100.0, "thousand": 0.0001,
                 "thousands": 0.0001, "rupees": 1e-7, "inr": 1e-7}


def pct_change(cur: Optional[float], base: Optional[float]) -> dict:
    """Percent change with honest handling of zero and negative bases."""
    if cur is None or base is None:
        return {"pct": None, "label": "—"}
    if base == 0:
        return {"pct": None, "label": "n.m."}
    if base < 0 <= cur:
        return {"pct": None, "label": "turned positive"}
    if base > 0 > cur:
        return {"pct": None, "label": "turned negative"}
    if base < 0 and cur < 0:
        p = (cur - base) / abs(base) * 100
        return {"pct": round(p, 1), "label": f"{'narrowed' if p > 0 else 'widened'} {abs(p):.0f}%"}
    p = (cur / base - 1) * 100
    return {"pct": round(p, 1), "label": f"{p:+.1f}%"}


def _f(x) -> Optional[float]:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def headline_numbers(period: dict, factor: float, lender: bool) -> dict:
    rev = _f(period.get("revenue_from_operations"))
    exp = _f(period.get("total_expenses"))
    fin = _f(period.get("finance_costs"))
    dep = _f(period.get("depreciation"))
    oth = _f(period.get("other_income")) or 0.0
    parts_read = fin is not None and dep is not None   # EBITDA needs both; never assume zero
    fin, dep = fin or 0.0, dep or 0.0
    pbt = _f(period.get("pbt"))
    pat = _f(period.get("pat_attributable_to_owners")) or _f(period.get("pat"))
    if lender:
        ebitda = _f(period.get("operating_profit_before_provisions"))
    elif not parts_read:
        ebitda = None
    elif rev is not None and exp is not None:
        ebitda = rev - exp + fin + dep            # operating: excludes other income
    elif pbt is not None:
        pbe = _f(period.get("profit_before_exceptional_and_tax"))
        ebitda = (pbe if pbe is not None else pbt) + fin + dep - oth
    else:
        ebitda = None
    scale = lambda v: None if v is None else round(v * factor, 2)
    return {"revenue": scale(rev), "ebitda": scale(ebitda), "pbt": scale(pbt), "pat": scale(pat)}


def results_card(extracted: dict) -> dict:
    """Turn a model's line-item extraction of a results filing into the card."""
    unit = str(extracted.get("unit") or "crore").lower().strip()
    factor = UNIT_TO_CRORE.get(unit, 1.0)
    lender = bool(extracted.get("is_lender"))
    by_role = {p.get("role"): p for p in extracted.get("periods") or []}
    cur, prev, ya = (by_role.get(r) for r in ("current", "previous_quarter", "year_ago_quarter"))
    if not cur:
        return {"ok": False, "reason": "current quarter not found in filing"}
    c = headline_numbers(cur, factor, lender)
    p = headline_numbers(prev, factor, lender) if prev else {}
    y = headline_numbers(ya, factor, lender) if ya else {}
    rows = []
    for key, label in (("revenue", "Revenue"), ("ebitda", "PPOP" if lender else "EBITDA"),
                       ("pbt", "PBT"), ("pat", "PAT")):
        rows.append({"key": key, "label": label, "value": c.get(key),
                     "qoq": pct_change(c.get(key), p.get(key)),
                     "yoy": pct_change(c.get(key), y.get(key))})
    margin = None
    if c.get("revenue") and c.get("ebitda") is not None and not lender:
        margin = round(c["ebitda"] / c["revenue"] * 100, 1)
    return {
        "ok": True, "unit": "₹ crore", "basis": extracted.get("basis") or "consolidated",
        "quarter": extracted.get("quarter"), "lender": lender, "rows": rows,
        "ebitda_margin": margin,
        "ebitda_note": ("Pre-provision operating profit shown for lenders; EBITDA is not meaningful for banks/NBFCs."
                        if lender else "EBITDA = revenue − total expenses + finance costs + depreciation (excludes other income)."),
        "note": extracted.get("notes") or "",
    }


def cross_check(card: dict, quarters: dict) -> Optional[bool]:
    """Compare the card's revenue/PAT with the exchange-derived quarterly table."""
    q = card.get("quarter")
    if not q or q not in (quarters or {}).get("periods", []):
        return None
    i = quarters["periods"].index(q)
    ok = True
    for key in ("revenue", "pat"):
        a = next((r["value"] for r in card["rows"] if r["key"] == key), None)
        b = (quarters["rows"].get(key) or [None] * (i + 1))[i]
        if a is None or b is None:
            continue
        if abs(a - b) > max(1.0, 0.03 * abs(b)):
            ok = False
    return ok


def complete_from_table(card: dict, quarters: dict, lender: bool = False) -> dict:
    """Make a results card trustworthy using the exchange-derived quarterly table.

    - If the filing could not be read, or its numbers disagree with the exchange
      data, the card is rebuilt from the table and says so.
    - Otherwise any line the model left blank is filled from the table for the
      same quarter, with its QoQ/YoY from the table too.
    Lenders' pre-provision profit is never filled: the table has no such line.
    """
    q = card.get("quarter")
    periods = (quarters or {}).get("periods") or []
    rows = (quarters or {}).get("rows") or {}
    if not q or q not in periods:
        return card

    def val(key, quarter):
        if quarter not in periods:
            return None
        arr = rows.get(key) or []
        i = periods.index(quarter)
        return arr[i] if i < len(arr) else None

    labels = (("revenue", "Revenue"), ("ebitda", "PPOP" if lender else "EBITDA"), ("pbt", "PBT"), ("pat", "PAT"))
    if not card.get("ok") or card.get("cross_check") is False:
        out_rows = []
        for key, label in labels:
            v = None if (lender and key == "ebitda") else val(key, q)
            out_rows.append({"key": key, "label": label, "value": v, "src": "table",
                             "qoq": pct_change(v, None if v is None else val(key, prev_quarter(q))),
                             "yoy": pct_change(v, None if v is None else val(key, year_ago(q)))})
        rev, eb = val("revenue", q), val("ebitda", q)
        return {**card, "ok": True, "rows": out_rows, "lender": lender, "unit": "₹ crore",
                "ebitda_margin": round(eb / rev * 100, 1) if rev and eb is not None and not lender else None,
                "source": "table", "cross_check": None,
                "note": "From the exchange's quarterly data: the filing itself could not be read reliably."}
    filled = []
    for r in card.get("rows", []):
        if lender and r["key"] == "ebitda":
            continue
        v = val(r["key"], q)
        mine = r.get("value")
        off = mine is not None and v and abs(mine / v - 1) > 0.08   # filing line disagrees with the exchange
        if mine is None or off:
            if v is not None:
                r.update({"value": v, "src": "table", "qoq": pct_change(v, val(r["key"], prev_quarter(q))),
                          "yoy": pct_change(v, val(r["key"], year_ago(q)))})
                filled.append(r["label"])
    if filled:
        card["filled_from_table"] = filled
        if not lender:
            rv = next((r["value"] for r in card["rows"] if r["key"] == "revenue"), None)
            ev = next((r["value"] for r in card["rows"] if r["key"] == "ebitda"), None)
            if rv and ev is not None:
                card["ebitda_margin"] = round(ev / rv * 100, 1)
    return card


# ---- quarterly table helpers (delivered side of the ledger) ---------------

def series(quarters: dict, key: str) -> dict[str, Optional[float]]:
    return dict(zip(quarters.get("periods", []), (quarters.get("rows", {}).get(key) or [])))


def fy_quarters(fy: int) -> list[str]:
    return [f"Q{q} FY{fy:02d}" for q in (1, 2, 3, 4)]


def scope_of(horizon: str) -> str:
    h = (horizon or "").upper().replace(" ", "")
    if h.startswith("H1"):
        return "h1"
    if h.startswith("H2"):
        return "h2"
    if h.startswith("Q"):
        return "quarter"
    return "fy"


def actual_for(metric: str, basis: str, horizon_end: Optional[str], quarters: dict,
               latest: Optional[str], scope: str = "fy") -> Optional[dict]:
    """Compute a delivered value from the table where the metric allows it.

    scope: "fy" | "h1" | "h2" | "quarter" — which quarters the promise covers.
    Returns {value, unit, period, ytd: bool, note} or None if not computable.
    Constant-currency guidance cannot be checked against INR numbers: None.
    """
    if not quarters or not quarters.get("periods") or basis in ("constant_currency",):
        return None
    rev, ebitda, pat = series(quarters, "revenue"), series(quarters, "ebitda"), series(quarters, "pat")
    target_q = horizon_end or latest
    if not target_q:
        return None
    fy, q = qkey(target_q)
    wanted = {"fy": fy_quarters(fy), "h1": fy_quarters(fy)[:2], "h2": fy_quarters(fy)[2:],
              "quarter": [target_q]}.get(scope, fy_quarters(fy))
    avail = [p for p in wanted if rev.get(p) is not None]
    if latest:
        avail = [p for p in avail if qkey(p) <= qkey(latest)]

    def ssum(s, ps):
        vals = [s.get(p) for p in ps]
        return None if not ps or any(v is None for v in vals) else sum(vals)

    periods = avail
    ytd = len(periods) < len(wanted)
    name = {"fy": f"FY{fy:02d}", "h1": f"H1 FY{fy:02d}", "h2": f"H2 FY{fy:02d}"}.get(scope, target_q)
    label = name + (f" so far ({len(periods)} of {len(wanted)} qtrs)" if ytd and periods else "")
    if not periods:
        return None
    prior = [year_ago(p) for p in periods]

    if metric == "revenue_growth":
        a, b = ssum(rev, periods), ssum(rev, prior)
        if a is None or not b:
            return None
        return {"value": round((a / b - 1) * 100, 1), "unit": "%", "period": label, "ytd": ytd,
                "note": "Reported revenue growth vs same period last year (₹, exchange data)."}
    if metric == "pat_growth":
        a, b = ssum(pat, periods), ssum(pat, prior)
        if a is None or not b or b <= 0:
            return None
        return {"value": round((a / b - 1) * 100, 1), "unit": "%", "period": label, "ytd": ytd,
                "note": "Net profit growth vs same period last year (exchange data)."}
    if metric == "ebitda_margin":
        a, r = ssum(ebitda, periods), ssum(rev, periods)
        if a is None or not r:
            return None
        return {"value": round(a / r * 100, 1), "unit": "%", "period": label, "ytd": ytd,
                "note": "Operating (EBITDA) margin from exchange data."}
    return None
