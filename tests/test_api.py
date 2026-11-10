"""The on-demand research path, end to end over HTTP, against fictional fakes:
company -> one ledger step per transcript -> finalize."""
import importlib.util
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path))
    import fakes
    fakes.install(monkeypatch.setattr)
    spec = importlib.util.spec_from_file_location("devserver", ROOT / "dev" / "server.py")
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    # api modules import sources at load time: patch their bound names too
    for name in ("company", "ledger_step", "ledger_finalize"):
        cls = dev.api_class(name)
    import api_company  # noqa: F401  (registered by spec loader name)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dev.Dev)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", dev
    srv.shutdown()


def call(base, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_research_flow(server, monkeypatch):
    base, dev = server
    import fakes
    mod = sys.modules["api_company"]
    monkeypatch.setattr(mod.screener, "fetch_company", fakes.fetch_company)
    monkeypatch.setattr(mod.prices, "daily", fakes.daily)
    step_mod = sys.modules["api_ledger_step"]
    monkeypatch.setattr(step_mod, "download_attachment", fakes.download_attachment)

    st, co = call(base, "/api/company?t=nwcable")
    assert st == 200 and co["name"] == "Northwind Cables Ltd" and len(co["transcripts"]) == 5
    state = None
    for t in reversed(co["transcripts"]):
        st, out = call(base, "/api/ledger_step", {"state": state, "symbol": "NWCABLE", "name": co["name"],
                                                  "quarter": t["quarter"], "url": t["url"]})
        assert st == 200, out
        state = out["state"]
    st, led = call(base, "/api/ledger_finalize", {"state": state, "quarters": co["quarters"], "latest": co["latest_quarter"]})
    assert st == 200
    assert led["counts"]["missed"] == 1 and led["counts"]["dropped"] == 1
    assert led["credibility"]


def test_bad_inputs(server):
    base, _ = server
    st, out = call(base, "/api/company?t=not%20a%20symbol!")
    assert st == 400 and "NSE symbol" in out["error"]
    st, out = call(base, "/api/ledger_step", {"symbol": "X"})
    assert st == 400
    st, out = call(base, "/api/ledger_finalize", {})
    assert st == 400


def test_static_and_fixture_paths(server):
    base, _ = server
    with urllib.request.urlopen(base + "/index.html", timeout=5) as r:
        assert r.status == 200


def test_step_refuses_unlisted_urls(server, monkeypatch):
    base, _ = server
    import fakes
    monkeypatch.setattr(sys.modules["api_ledger_step"].screener, "fetch_company", fakes.fetch_company)
    st, out = call(base, "/api/ledger_step", {"symbol": "NWCABLE", "quarter": "Q2 FY27",
                                              "url": "https://169.254.169.254/latest/meta-data"})
    assert st == 400 and "not listed" in out["error"]
