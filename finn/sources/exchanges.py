"""Corporate announcements from BSE (primary) and NSE (fallback).

Both exchanges expose the JSON their own websites use. BSE is usually more
tolerant of cloud servers; NSE needs a cookie from its home page first.
Both are normalised to one shape:
  {id, source, symbol, ts, headline, raw_category, raw_subcategory, attachment}
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

import requests

from .. import http

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{}"
BSE_ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{}"
BSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}

NSE_HOME = "https://www.nseindia.com/"
NSE_API = "https://www.nseindia.com/api/corporate-announcements"


def _iso(ts: Optional[str], fmts: tuple[str, ...]) -> Optional[str]:
    if not ts:
        return None
    t = ts.split(".")[0].strip()
    for f in fmts:
        try:
            return dt.datetime.strptime(t, f).replace(tzinfo=IST).isoformat()
        except ValueError:
            continue
    return None


_bse_blocked = False


def _bse_get(params: dict):
    """Browser-like session first (gets past BSE's bot filter), plain requests second."""
    last = None
    browser = http.browser_session()
    for sess in ([browser] if browser else []) + [None]:
        try:
            return http.get(BSE_API, params=params, headers=BSE_HEADERS, expect="json", sess=sess, retries=1)
        except http.FetchError as e:
            last = e
            if e.status not in (401, 403, None):
                raise
    raise last


def bse_announcements(scrip: str, symbol: str, start: dt.date, end: dt.date,
                      max_pages: int = 6) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "pageno": page, "strCat": "-1", "subcategory": "-1",
            "strPrevDate": start.strftime("%Y%m%d"), "strToDate": end.strftime("%Y%m%d"),
            "strSearch": "P", "strscrip": scrip, "strType": "C",
        }
        r = _bse_get(params)
        rows = (r.json() or {}).get("Table") or []
        if not rows:
            break
        for a in rows:
            att = a.get("ATTACHMENTNAME") or ""
            out.append({
                "id": f"BSE-{a.get('NEWSID') or att or a.get('HEADLINE','')[:40]}",
                "source": "BSE",
                "symbol": symbol,
                "ts": _iso(a.get("NEWS_DT") or a.get("DissemDT") or a.get("DT_TM"),
                           ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S")),
                "headline": (a.get("NEWSSUB") or a.get("HEADLINE") or "").strip(),
                "detail": (a.get("HEADLINE") or "").strip(),
                "raw_category": (a.get("CATEGORYNAME") or "").strip(),
                "raw_subcategory": (a.get("SUBCATNAME") or "").strip(),
                "attachment": BSE_ATTACH.format(att) if att else None,
            })
        if len(rows) < 20:
            break
    return out


_nse_session: Optional[requests.Session] = None


def _nse() -> requests.Session:
    global _nse_session
    if _nse_session is None:
        s = requests.Session()
        s.headers.update(http.BASE_HEADERS)
        s.headers.update({"Referer": NSE_HOME})
        s.get(NSE_HOME, timeout=20)  # sets the cookies the API requires
        _nse_session = s
    return _nse_session


def nse_announcements(symbol: str, start: dt.date, end: dt.date) -> list[dict]:
    params = {"index": "equities", "symbol": symbol,
              "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
    r = http.get(NSE_API, params=params, sess=_nse(), expect="json")
    rows = r.json() or []
    if isinstance(rows, dict):
        rows = rows.get("data") or []
    out = []
    for a in rows:
        out.append({
            "id": f"NSE-{a.get('seq_id') or a.get('attchmntFile','')[-40:]}",
            "source": "NSE",
            "symbol": symbol,
            "ts": _iso(a.get("sort_date") or a.get("an_dt"),
                       ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S")),
            "headline": (a.get("attchmntText") or a.get("desc") or "").strip(),
            "detail": "",
            "raw_category": (a.get("desc") or "").strip(),
            "raw_subcategory": "",
            "attachment": a.get("attchmntFile") or None,
        })
    return out


def announcements(symbol: str, bse_code: Optional[str], start: dt.date, end: dt.date) -> tuple[list[dict], str]:
    """Try BSE then NSE. Returns (items, source_used_or_error)."""
    global _bse_blocked
    errors = []
    if bse_code and not _bse_blocked:
        try:
            return bse_announcements(bse_code, symbol, start, end), "BSE"
        except http.FetchError as e:
            errors.append(f"BSE {e.status}")
            if e.status in (401, 403):
                _bse_blocked = True  # don't knock on a closed door for every company
    try:
        return nse_announcements(symbol, start, end), "NSE"
    except (http.FetchError, requests.RequestException) as e:
        errors.append(f"NSE {getattr(e, 'status', '')}")
    raise http.FetchError(symbol, None, "announcements unavailable: " + ", ".join(errors))


def download_attachment(url: str) -> bytes:
    try:
        return http.get(url, expect="pdf", headers=BSE_HEADERS if "bseindia" in url else None,
                        sess=_nse() if "nseindia" in url else None, timeout=40).content
    except http.FetchError as e:
        if "AttachLive" in url and e.status in (404, None):
            return http.get(url.replace("AttachLive", "AttachHis"), expect="pdf",
                            headers=BSE_HEADERS, timeout=40).content
        raise


def clean_headline(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:280]
