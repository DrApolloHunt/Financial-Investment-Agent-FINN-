"""screener.in company page: names, exchange codes, quarterly table, and links
to primary documents (concall transcripts, annual reports).

The quarterly table is standardised from the company's own filings; FINN uses
it only as the "delivered" side of the ledger and never reads screener's own
commentary. Transcripts and annual reports are fetched from the exchange URLs
screener links to.
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from .. import http
from ..periods import parse_month_year, quarter_discussed_on_call, quarter_label, qkey

BASE = "https://www.screener.in/company/{sym}/{variant}"

# Canonical keys for the rows FINN uses. Lenders use different labels.
ROW_KEYS = {
    "sales": "revenue", "revenue": "revenue",
    "expenses": "expenses",
    "operating profit": "ebitda", "financing profit": "ebitda",
    "opm %": "margin", "financing margin %": "margin",
    "other income": "other_income",
    "interest": "interest",
    "depreciation": "depreciation",
    "profit before tax": "pbt",
    "tax %": "tax_pct",
    "net profit": "pat",
    "eps in rs": "eps",
    "gross npa %": "gnpa", "net npa %": "nnpa",
}


def _num(text: str) -> Optional[float]:
    t = (text or "").replace(",", "").replace("%", "").replace("\xa0", " ").strip()
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _clean_label(text: str) -> str:
    t = (text or "").replace("\xa0", " ").replace("+", " ")
    return re.sub(r"\s+", " ", t).strip().lower()


def parse_company_html(html: str, symbol: str, url: str = "") -> dict:
    soup = BeautifulSoup(html, "lxml")
    out: dict = {"symbol": symbol.upper(), "url": url}

    h1 = soup.find("h1")
    out["name"] = h1.get_text(" ", strip=True) if h1 else symbol.upper()

    page_text = soup.get_text(" ", strip=True)
    m = re.search(r"BSE:\s*(\d{6})", page_text)
    out["bse_code"] = m.group(1) if m else None
    m = re.search(r"NSE:\s*([A-Z0-9&\-]+)", page_text)
    out["nse_symbol"] = m.group(1) if m else symbol.upper()
    out["is_lender"] = bool(re.search(r"Financing Profit|Financing Margin", html))

    out["quarters"] = _parse_quarters(soup)
    out["transcripts"] = _parse_concalls(soup)
    out["annual_reports"] = _parse_annual_reports(soup)
    out["annual"] = {name: _parse_annual(soup, sec_id, keys) for name, (sec_id, keys) in ANNUAL.items()}
    out["top_ratios"] = _parse_top_ratios(soup)
    return out


# ---- annual tables (from annual reports, standardised by screener.in) ----------

ANNUAL = {
    "pl": ("profit-loss", {
        "sales": "revenue", "revenue": "revenue", "expenses": "expenses",
        "operating profit": "ebitda", "financing profit": "ebitda",
        "opm %": "margin", "financing margin %": "margin", "other income": "other_income",
        "interest": "interest", "depreciation": "depreciation", "profit before tax": "pbt",
        "tax %": "tax_pct", "net profit": "pat", "eps in rs": "eps", "dividend payout %": "payout"}),
    "bs": ("balance-sheet", {
        "equity capital": "equity_capital", "reserves": "reserves", "borrowings": "borrowings",
        "deposits": "deposits", "other liabilities": "other_liabilities",
        "total liabilities": "total_liabilities", "fixed assets": "fixed_assets", "cwip": "cwip",
        "investments": "investments", "other assets": "other_assets", "total assets": "total_assets"}),
    "cf": ("cash-flow", {
        "cash from operating activity": "cfo", "cash from investing activity": "cfi",
        "cash from financing activity": "cff", "net cash flow": "net_cash"}),
    "ratios": ("ratios", {
        "debtor days": "debtor_days", "inventory days": "inventory_days", "days payable": "payable_days",
        "cash conversion cycle": "ccc", "working capital days": "wc_days", "roce %": "roce", "roe %": "roe"}),
}


def _year_label(h: str) -> str:
    """'Mar 2025' -> 'FY25'; 'TTM' stays; other month-ends keep their name."""
    h = (h or "").strip()
    if h.upper() == "TTM":
        return "TTM"
    my = parse_month_year(h)
    if my and my[0] == 3:
        return f"FY{my[1] % 100:02d}"
    return h


def _parse_annual(soup, sec_id: str, keys: dict) -> dict:
    sec = soup.find(id=sec_id)
    table = None
    if sec:
        table = sec.find("table", class_=re.compile("data-table")) or sec.find("table")
    if not table or not table.find("thead"):
        return {"periods": [], "rows": {}}
    head = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")][1:]
    periods = [_year_label(h) for h in head]
    rows: dict[str, list] = {}
    for tr in (table.find("tbody") or table).find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        key = keys.get(_clean_label(tds[0].get_text(" ", strip=True)))
        if key and key not in rows:
            vals = [_num(td.get_text(" ", strip=True)) for td in tds[1:]]
            rows[key] = (vals + [None] * len(periods))[:len(periods)]
    return {"periods": periods, "rows": rows}


TOP_KEYS = {"market cap": "market_cap_cr", "current price": "price", "stock p/e": "pe",
            "book value": "book_value", "dividend yield": "dividend_yield", "roce": "roce", "roe": "roe",
            "face value": "face_value"}


def _parse_top_ratios(soup) -> dict:
    ul = soup.find(id="top-ratios")
    out: dict = {}
    if not ul:
        return out
    for li in ul.find_all("li"):
        name_el = li.find(class_="name")
        name = _clean_label(name_el.get_text(" ", strip=True) if name_el else li.get_text(" ", strip=True).split("₹")[0])
        nums = [_num(n.get_text(" ", strip=True).replace("₹", "").replace("Cr.", "").replace("%", ""))
                for n in li.find_all(class_="number")]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue
        if name.startswith("high / low") and len(nums) >= 2:
            out["high"], out["low"] = nums[0], nums[1]
            continue
        key = TOP_KEYS.get(name)
        if key:
            out[key] = nums[0]
    return out


def _parse_quarters(soup) -> dict:
    sec = soup.find(id="quarters")
    table = sec.find("table") if sec else None
    if not table:
        return {"periods": [], "rows": {}}
    head = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")] if table.find("thead") else []
    labels = [quarter_label(h) for h in head[1:]]
    rows: dict[str, list] = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        key = ROW_KEYS.get(_clean_label(tds[0].get_text(" ", strip=True)))
        if not key:
            continue
        rows[key] = [_num(td.get_text(" ", strip=True)) for td in tds[1:]]
    keep = [i for i, l in enumerate(labels) if l]
    return {"periods": [labels[i] for i in keep],
            "rows": {k: [v[i] if i < len(v) else None for i in keep] for k, v in rows.items()}}


def _section(soup, cls: str, heading: str):
    el = soup.find(class_=re.compile(rf"\b{cls}\b"))
    if el:
        return el
    h = soup.find(lambda t: t.name in ("h2", "h3", "h4") and t.get_text(strip=True).lower() == heading)
    return h.parent if h else None


def _parse_concalls(soup) -> list[dict]:
    sec = _section(soup, "concalls", "concalls")
    if not sec:
        return []
    out = []
    for li in sec.find_all("li"):
        text = li.get_text(" ", strip=True)
        my = parse_month_year(text)
        link = None
        for a in li.find_all("a"):
            label = (a.get_text(" ", strip=True) + " " + (a.get("title") or "")).lower()
            if "transcript" in label and a.get("href"):
                link = a["href"]
                break
        if not my or not link:
            continue
        month, year = my
        call_label = f"{['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][month]} {year}"
        out.append({"call_month": call_label,
                    "quarter": quarter_discussed_on_call(call_label),
                    "url": link})
    # newest first, one transcript per quarter discussed
    out.sort(key=lambda d: qkey(d["quarter"] or ""), reverse=True)
    seen, uniq = set(), []
    for d in out:
        if d["quarter"] and d["quarter"] not in seen:
            seen.add(d["quarter"])
            uniq.append(d)
    return uniq


def _parse_annual_reports(soup) -> list[dict]:
    sec = _section(soup, "annual-reports", "annual reports")
    if not sec:
        return []
    out = []
    for a in sec.find_all("a"):
        href = a.get("href")
        if href and href.startswith("http"):
            label = a.find(string=True, recursive=False) or a.get_text(" ", strip=True)
            out.append({"label": str(label).strip(), "url": href})
    return out


def fetch_company(symbol: str) -> dict:
    """Consolidated view if available, else standalone."""
    sym = symbol.upper().strip()
    last_err: Optional[Exception] = None
    for variant in ("consolidated/", ""):
        url = BASE.format(sym=sym, variant=variant)
        try:
            r = http.get(url, expect="html", headers={"Referer": "https://www.screener.in/"})
        except http.FetchError as e:
            last_err = e
            if e.status == 404:
                continue
            raise
        data = parse_company_html(r.text, sym, url)
        data["basis"] = "consolidated" if variant else "standalone"
        if data["quarters"]["periods"]:
            return data
        last_err = http.FetchError(url, r.status_code, "no quarterly table on page")
    raise last_err or http.FetchError(sym, None, "company not found on screener.in")
