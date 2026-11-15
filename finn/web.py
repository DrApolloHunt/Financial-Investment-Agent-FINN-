"""The research API: three endpoints, served by one WSGI app (app.py).

  GET  /api/company?t=SYMBOL   identity, quarterly table, transcript links, prices
  POST /api/ledger_step        read ONE earnings-call transcript into the ledger
  POST /api/ledger_finalize    statuses (rules) + verdicts (one reasoning call)

The browser calls ledger_step once per transcript, oldest first, so the investor
watches the ledger fill in. Standard library only on the request path.
"""
from __future__ import annotations

import json
import mimetypes
import re
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs

from . import business as biz
from . import fundamentals, gemini, ledger
from .sources import exchanges, prices, screener

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,20}$")
N_CALLS = 5
MAX_BODY = 2_000_000

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def symbol(raw) -> str:
    s = str(raw or "").upper().strip().removesuffix(".NS").removesuffix(".BO")
    if not SYMBOL.match(s):
        raise ApiError(400, "Give an NSE symbol, e.g. INFY or DIXON.")
    return s


# ---- endpoints -------------------------------------------------------------------

def company(q: dict) -> dict:
    """Any NSE company, on demand. No model call: the cheap first step."""
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
    co["fundamentals"] = fundamentals.summarize(co)
    co["latest_quarter"] = co["quarters"]["periods"][-1] if co["quarters"]["periods"] else None
    return co


_listed: dict[str, tuple[float, set]] = {}


def listed_transcripts(sym: str) -> set:
    """The server only fetches transcript URLs screener.in lists for this company,
    never an arbitrary URL from the browser. Memoised per warm instance."""
    hit = _listed.get(sym)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    urls = {t["url"] for t in screener.fetch_company(sym)["transcripts"]}
    _listed[sym] = (time.time(), urls)
    return urls


def ledger_step(body: dict) -> dict:
    sym = symbol(body.get("symbol"))
    url, quarter = body.get("url"), body.get("quarter")
    if not url or not str(url).startswith("https://") or not quarter:
        raise ApiError(400, "Need a transcript url and quarter.")
    if url not in listed_transcripts(sym):
        raise ApiError(400, "That transcript is not listed for this company.")
    state = body.get("state") or ledger.new_state(sym, body.get("name") or sym)
    if state.get("symbol") != sym:
        raise ApiError(400, "State belongs to a different company.")
    state = ledger.read_call(state, quarter, url, exchanges.download_attachment)
    new = [p for p in state["promises"] if p["made_in"] == quarter]
    return {"state": state, "found": len(new),
            "updated": sum(1 for p in state["promises"] for e in p["history"]
                           if e["quarter"] == quarter and e["kind"] != "not_mentioned")}


def business(body: dict) -> dict:
    """Business snapshot from the latest annual report screener lists for the company."""
    sym = symbol(body.get("symbol"))
    co = screener.fetch_company(sym)
    ar = biz.latest_report(co.get("annual_reports") or [])
    if not ar:
        raise ApiError(404, "No annual report is listed for this company.")
    out = biz.read_business(co["name"], ar["url"], ar.get("label", ""))
    if not out:
        raise ApiError(502, "The annual report could not be read.")
    return out


def ledger_finalize(body: dict) -> dict:
    state = body.get("state")
    if not state or "promises" not in state:
        raise ApiError(400, "Need a ledger state.")
    ctx = ledger.context_for({"fundamentals": body.get("fundamentals"), "business": body.get("business")})
    return ledger.finalize(state, body.get("quarters") or {}, body.get("latest"), use_model=True, context=ctx)


ROUTES = {
    ("GET", "/api/company"): company,
    ("POST", "/api/ledger_step"): ledger_step,
    ("POST", "/api/ledger_finalize"): ledger_finalize,
    ("POST", "/api/business"): business,
}


def run(fn, arg) -> tuple[int, dict]:
    """Call an endpoint; turn failures into plain-language JSON errors.
    A person is waiting, so the model client moves to its fallback at once (gemini.QUICK)."""
    token = gemini.QUICK.set(True)
    try:
        return 200, fn(arg)
    except ApiError as e:
        return e.status, {"error": e.message}
    except Exception as e:  # never leak a stack trace to the client
        traceback.print_exc()
        name = type(e).__name__
        msg = {"NoKey": "Server has no GEMINI_API_KEY configured.",
               "FetchError": f"A data source did not respond: {str(e)[:160]}",
               "GeminiError": f"The AI model is unavailable right now (free-tier limits?): {str(e)[:160]}"}.get(name, f"{name}: {str(e)[:160]}")
        return 502, {"error": msg}
    finally:
        gemini.QUICK.reset(token)


# ---- WSGI app ----------------------------------------------------------------------

def _respond(start_response, status: int, body: bytes, ctype: str, cache: str = "no-store"):
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
              413: "Payload Too Large", 502: "Bad Gateway"}.get(status, "OK")
    start_response(f"{status} {reason}", [("Content-Type", ctype), ("Content-Length", str(len(body))),
                                          ("Cache-Control", cache)])
    return [body]


def _json(start_response, status: int, obj) -> list:
    return _respond(start_response, status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")


def _static(path: str, start_response) -> list:
    """Fallback for the static app (the platform's CDN normally serves public/)."""
    rel = path.lstrip("/") or "index.html"
    target = (PUBLIC / rel).resolve()
    if PUBLIC.resolve() not in target.parents and target != PUBLIC.resolve():
        return _respond(start_response, 404, b"Not found", "text/plain")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return _respond(start_response, 404, b"Not found", "text/plain")
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype.endswith(("json", "javascript")):
        ctype += "; charset=utf-8"
    cache = "public, max-age=60" if "/data/" in path else "public, max-age=300"
    return _respond(start_response, 200, target.read_bytes(), ctype, cache)


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = (environ.get("PATH_INFO") or "/").rstrip("/") or "/"
    fn = ROUTES.get((method, path))
    if fn is None and path.startswith("/api/"):
        known = any(p == path for (_, p) in ROUTES)
        return _json(start_response, 405 if known else 404,
                     {"error": "method not allowed" if known else "no such endpoint"})
    if fn is None:
        return _static(path, start_response)
    if method == "GET":
        arg = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
    else:
        n = int(environ.get("CONTENT_LENGTH") or 0)
        if n > MAX_BODY:
            return _json(start_response, 413, {"error": "request too large"})
        try:
            arg = json.loads(environ["wsgi.input"].read(n) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _json(start_response, 400, {"error": "invalid JSON"})
    status, obj = run(fn, arg)
    return _json(start_response, status, obj)
