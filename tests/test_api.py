"""The research API (one WSGI app, as Vercel runs it), against fictional fakes:
company -> one ledger step per transcript -> finalize."""
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev"))

import app as entry  # noqa: E402  (the Vercel entrypoint itself)


@pytest.fixture(autouse=True)
def fakes_on(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path))
    import fakes
    fakes.install(monkeypatch.setattr)
    from finn import web
    web._listed.clear()


def call(path, body=None, method=None):
    method = method or ("POST" if body is not None else "GET")
    p, _, q = path.partition("?")
    data = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": p, "QUERY_STRING": q,
           "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data)}
    got = {}

    def start_response(status, headers):
        got["status"], got["headers"] = int(status.split()[0]), dict(headers)
    out = b"".join(entry.app(env, start_response))
    ctype = got["headers"].get("Content-Type", "")
    return got["status"], (json.loads(out) if "json" in ctype else out)


def test_research_flow():
    st, co = call("/api/company?t=nwcable")
    assert st == 200 and co["name"] == "Northwind Cables Ltd" and len(co["transcripts"]) == 5
    state = None
    for t in reversed(co["transcripts"]):
        st, out = call("/api/ledger_step", {"state": state, "symbol": "NWCABLE", "name": co["name"],
                                            "quarter": t["quarter"], "url": t["url"]})
        assert st == 200, out
        state = out["state"]
    st, biz = call("/api/business", {"symbol": "NWCABLE"})
    assert st == 200 and biz["segments"] and biz["what_it_does"]
    st, led = call("/api/ledger_finalize", {"state": state, "quarters": co["quarters"], "latest": co["latest_quarter"],
                                            "fundamentals": co["fundamentals"], "business": biz})
    assert st == 200
    assert led["counts"]["missed"] == 1 and led["counts"]["dropped"] == 1
    assert led["credibility"] and len(led["bull"]) == 3 and len(led["bear"]) == 3
    assert co["fundamentals"]["balance"]["notes"]


def test_bad_inputs():
    st, out = call("/api/company?t=not%20a%20symbol!")
    assert st == 400 and "NSE symbol" in out["error"]
    assert call("/api/ledger_step", {"symbol": "X"})[0] == 400
    assert call("/api/ledger_finalize", {})[0] == 400
    assert call("/api/company", method="POST", body={})[0] == 405
    assert call("/api/nope")[0] == 404


def test_step_refuses_unlisted_urls():
    st, out = call("/api/ledger_step", {"symbol": "NWCABLE", "quarter": "Q2 FY27",
                                        "url": "https://169.254.169.254/latest/meta-data"})
    assert st == 400 and "not listed" in out["error"]


def test_static_fallback_and_no_traversal():
    st, body = call("/")
    assert st == 200 and b"<title>FINN</title>" in body
    st, body = call("/js/app.js")
    assert st == 200 and b"import" in body
    assert call("/../config/categories.json")[0] == 404
    assert call("/data/../../app.py")[0] == 404
