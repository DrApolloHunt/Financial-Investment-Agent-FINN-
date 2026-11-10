"""Small HTTP helper: browser-like headers, retries, timeouts.

All network access in FINN goes through `get()` so that tests can patch a
single function and so that every source shares the same politeness rules.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/json,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


class FetchError(RuntimeError):
    def __init__(self, url: str, status: Optional[int], detail: str = ""):
        self.url, self.status, self.detail = url, status, detail
        super().__init__(f"{status or 'ERR'} fetching {url} {detail}".strip())


_session: Optional[requests.Session] = None
_browser = False  # False = not tried yet, None = unavailable


def browser_session():
    """A session with a Chrome-like TLS fingerprint, if curl_cffi is installed
    (it comes with yfinance). BSE's API sits behind a bot filter that refuses
    plain Python clients even from home connections. Returns None if unavailable."""
    global _browser
    if _browser is False:
        try:
            from curl_cffi import requests as creq
            _browser = creq.Session(impersonate="chrome")
            _browser.headers.update({"Accept-Language": BASE_HEADERS["Accept-Language"]})
        except Exception:
            _browser = None
    return _browser


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(BASE_HEADERS)
    return _session


def get(url: str, *, params=None, headers=None, timeout=25, retries=2,
        expect: str = "any", sess: Optional[requests.Session] = None) -> requests.Response:
    """GET with retries on 429/5xx and network errors.

    expect: "json" | "pdf" | "html" | "any" — used only to give clearer errors
    when a site returns an HTML block page instead of the expected payload.
    """
    s = sess or session()
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = s.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise FetchError(url, r.status_code, r.text[:160].replace("\n", " "))
            ctype = r.headers.get("content-type", "")
            if expect == "pdf" and "pdf" not in ctype and not r.content[:5] == b"%PDF-":
                raise FetchError(url, r.status_code, f"expected PDF, got {ctype or 'unknown'}")
            if expect == "json" and "json" not in ctype and not r.text.lstrip().startswith(("{", "[")):
                raise FetchError(url, r.status_code, f"expected JSON, got {ctype or 'unknown'}")
            return r
        except FetchError:
            raise
        except Exception as e:  # network-level, from requests or curl_cffi
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise FetchError(url, None, str(last))
