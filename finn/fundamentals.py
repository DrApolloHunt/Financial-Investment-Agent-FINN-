"""Financial snapshot, trajectory, balance sheet and cash quality, in code.

Inputs are the annual tables from the companies' own filings (standardised by
screener.in). No model is involved: every number and every sentence here is
computed, so it can be checked and never invented.
"""
from __future__ import annotations

from typing import Optional

SOURCE = "Annual figures from the company's filings, standardised by screener.in."


def _fy(periods: list[str]) -> list[int]:
    """Indexes of full fiscal-year columns (drops TTM and half-year columns)."""
    return [i for i, p in enumerate(periods) if p.startswith("FY")]


def _series(tab: dict, key: str, idx: list[int]) -> list[Optional[float]]:
    row = (tab.get("rows") or {}).get(key) or []
    return [row[i] if i < len(row) else None for i in idx]


def cagr(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    if not first or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 1)


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or not b else round(a / b * 100, 1)


def _crore(v: Optional[float]) -> str:
    return "—" if v is None else f"₹{v:,.0f} cr"


def summarize(co: dict) -> Optional[dict]:
    annual = co.get("annual") or {}
    pl, bs, cf, ra = (annual.get(k) or {"periods": [], "rows": {}} for k in ("pl", "bs", "cf", "ratios"))
    if not pl.get("periods"):
        return None
    lender = bool(co.get("is_lender"))
    top = co.get("top_ratios") or {}

    # ---- trajectory: last ten fiscal years --------------------------------------------
    idx = _fy(pl["periods"])[-10:]
    years = [pl["periods"][i] for i in idx]
    rev, pat, eb = _series(pl, "revenue", idx), _series(pl, "pat", idx), _series(pl, "ebitda", idx)
    margin = [_pct(e, r) for e, r in zip(eb, rev)]
    traj: dict = {"years": years, "revenue": rev, "pat": pat, "margin": margin, "notes": []}
    for n in (5, 3):
        if len(years) > n:
            traj[f"rev_cagr_{n}y"] = cagr(rev[-1 - n], rev[-1], n)
            traj[f"pat_cagr_{n}y"] = cagr(pat[-1 - n], pat[-1], n)
    if traj.get("rev_cagr_5y") is not None:
        s = f"Revenue has compounded {traj['rev_cagr_5y']}% a year over five years"
        s += f" and net profit {traj['pat_cagr_5y']}%." if traj.get("pat_cagr_5y") is not None else "."
        traj["notes"].append(s)
    if len(years) > 5 and margin[-6] is not None and margin[-1] is not None and not lender:
        d = round(margin[-1] - margin[-6], 1)
        word = "widened" if d > 0.5 else "narrowed" if d < -0.5 else "held steady"
        traj["notes"].append(f"EBITDA margin {word}: {margin[-6]}% in {years[-6]} to {margin[-1]}% in {years[-1]}.")
    if traj.get("rev_cagr_3y") is not None and traj.get("rev_cagr_5y") is not None:
        d = traj["rev_cagr_3y"] - traj["rev_cagr_5y"]
        if abs(d) >= 2:
            traj["notes"].append(f"Growth is {'accelerating' if d > 0 else 'slowing'}: "
                                 f"{traj['rev_cagr_3y']}% a year over three years against {traj['rev_cagr_5y']}% over five.")

    # ---- financial snapshot -----------------------------------------------------------------
    ttm_i = pl["periods"].index("TTM") if "TTM" in pl["periods"] else (idx[-1] if idx else None)
    def at(tab, key, i):
        row = (tab.get("rows") or {}).get(key) or []
        return row[i] if i is not None and i < len(row) else None
    snap = {
        "period": pl["periods"][ttm_i] if ttm_i is not None else None,
        "revenue": at(pl, "revenue", ttm_i), "pat": at(pl, "pat", ttm_i),
        "margin": None if lender else _pct(at(pl, "ebitda", ttm_i), at(pl, "revenue", ttm_i)),
        "market_cap_cr": top.get("market_cap_cr"), "pe": top.get("pe"), "roe": top.get("roe"),
        "roce": top.get("roce"), "dividend_yield": top.get("dividend_yield"), "book_value": top.get("book_value"),
        "price": top.get("price"),
    }

    # ---- balance sheet ------------------------------------------------------------------------
    bidx = list(range(len(bs.get("periods") or [])))
    balance: dict = {"lender": lender, "notes": []}
    if bidx:
        last = bidx[-1]
        net_worth = (at(bs, "equity_capital", last) or 0) + (at(bs, "reserves", last) or 0) or None
        debt = at(bs, "borrowings", last)
        balance.update({"period": bs["periods"][last], "borrowings": debt, "net_worth": net_worth,
                        "total_assets": at(bs, "total_assets", last),
                        "debt_to_equity": None if lender or not net_worth or debt is None else round(debt / net_worth, 2)})
        b_idx = _fy(bs["periods"])
        if len(b_idx) > 5:
            balance["borrowings_5y_ago"] = at(bs, "borrowings", b_idx[-6])
            balance["since"] = bs["periods"][b_idx[-6]]
        if lender:
            balance["notes"].append("For a lender, borrowings and deposits are its raw material, so debt/equity is not a warning sign by itself.")
        elif balance["debt_to_equity"] is not None:
            de = balance["debt_to_equity"]
            tone = "almost debt-free" if de < 0.1 else "lightly geared" if de < 0.5 else "moderately geared" if de < 1 else "heavily geared"
            balance["notes"].append(f"Borrowings {_crore(debt)} against net worth {_crore(net_worth)}: debt/equity {de}, {tone}.")
        if balance.get("borrowings_5y_ago") is not None and debt is not None and not lender:
            then = balance["borrowings_5y_ago"]
            if then and abs(debt / then - 1) > 0.25:
                balance["notes"].append(f"Borrowings {'rose' if debt > then else 'fell'} from {_crore(then)} in {balance['since']}.")
        last_pl = idx[-1] if idx else None
        e, i_ = at(pl, "ebitda", last_pl), at(pl, "interest", last_pl)
        if e and i_ and not lender:
            balance["interest_cover"] = round(e / i_, 1)
    r_idx = _fy(ra.get("periods") or [])[-6:]
    if r_idx and not lender:
        balance["wc_years"] = [ra["periods"][i] for i in r_idx]
        balance["wc_days"] = [at(ra, "wc_days", i) for i in r_idx]
        balance["ccc"] = [at(ra, "ccc", i) for i in r_idx]
        w = [x for x in balance["wc_days"] if x is not None]
        if len(w) >= 2 and abs(w[-1] - w[0]) >= 10:
            balance["notes"].append(f"Working-capital days {'stretched' if w[-1] > w[0] else 'tightened'} from "
                                    f"{w[0]:.0f} to {w[-1]:.0f} over {len(w) - 1} years.")

    # ---- cash quality -------------------------------------------------------------------------------
    cidx = _fy(cf.get("periods") or [])[-5:]
    cash: dict = {"lender": lender, "notes": []}
    if cidx:
        cyears = [cf["periods"][i] for i in cidx]
        cfo = [at(cf, "cfo", i) for i in cidx]
        pat_map = dict(zip([pl["periods"][i] for i in _fy(pl["periods"])], [at(pl, "pat", i) for i in _fy(pl["periods"])]))
        cpat = [pat_map.get(y) for y in cyears]
        cash.update({"years": cyears, "cfo": cfo, "pat": cpat})
        pairs = [(c, p) for c, p in zip(cfo, cpat) if c is not None and p is not None]
        if pairs and sum(p for _, p in pairs) > 0:
            conv = round(sum(c for c, _ in pairs) / sum(p for _, p in pairs) * 100)
            cash["conversion"] = conv
            if lender:
                cash["notes"].append("Operating cash flow of a lender swings with loan growth, so cash conversion says little here.")
            else:
                verdict = ("profits are turning into cash" if conv >= 90 else
                           "most profit turns into cash" if conv >= 70 else
                           "a gap between profit and cash worth checking")
                cash["notes"].append(f"Over {len(pairs)} years, operating cash flow was {conv}% of reported profit: {verdict}.")
            neg = [y for (y, c) in zip(cyears, cfo) if c is not None and c < 0]
            if neg and not lender:
                cash["notes"].append(f"Operating cash flow was negative in {', '.join(neg)}.")

    return {"snapshot": snap, "trajectory": traj, "balance": balance, "cash": cash, "source": SOURCE}


def facts_for_prompt(f: Optional[dict]) -> str:
    """The computed facts, as plain lines, for grounding the bull/bear call."""
    if not f:
        return "(no annual figures)"
    lines = []
    s = f["snapshot"]
    lines.append(f"Snapshot ({s.get('period')}): revenue {_crore(s.get('revenue'))}, net profit {_crore(s.get('pat'))}, "
                 f"EBITDA margin {s.get('margin')}%, P/E {s.get('pe')}, ROE {s.get('roe')}%, ROCE {s.get('roce')}%.")
    for part in ("trajectory", "balance", "cash"):
        lines += f[part].get("notes", [])
    return "\n".join(lines)
