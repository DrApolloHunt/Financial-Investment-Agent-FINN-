"""Tiny helpers shared by the Vercel Python functions in /api and the local
dev server. Standard library only on the request path."""
from __future__ import annotations

import json
import re
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,20}$")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def symbol(raw) -> str:
    s = str(raw or "").upper().strip().removesuffix(".NS").removesuffix(".BO")
    if not SYMBOL.match(s):
        raise ApiError(400, "Give an NSE symbol, e.g. INFY or DIXON.")
    return s


def make_handler(get=None, post=None):
    """Build a BaseHTTPRequestHandler class from plain functions.

    get(query: dict) -> obj ; post(body: dict) -> obj
    """
    class handler(BaseHTTPRequestHandler):
        def _send(self, status, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _run(self, fn, arg):
            if fn is None:
                return self._send(405, {"error": "method not allowed"})
            try:
                self._send(200, fn(arg))
            except ApiError as e:
                self._send(e.status, {"error": e.message})
            except Exception as e:  # never leak a stack trace to the client
                traceback.print_exc()
                name = type(e).__name__
                msg = {"NoKey": "Server has no GEMINI_API_KEY configured.",
                       "FetchError": f"A data source did not respond: {str(e)[:160]}",
                       "GeminiError": f"The AI model is unavailable right now (free-tier limits?): {str(e)[:160]}"}.get(name, f"{name}: {str(e)[:160]}")
                self._send(502, {"error": msg})

        def do_GET(self):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            self._run(get, q)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                return self._send(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid JSON"})
            self._run(post, body)

        def log_message(self, *a):  # quiet
            pass

    return handler
