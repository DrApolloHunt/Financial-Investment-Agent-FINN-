"""Run the real pipeline end to end against fictional fakes (dev/fakes.py)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pipeline_full_run(tmp_path):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, str(ROOT / "dev" / "make_fixtures.py"), str(out)],
                       capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    feed = json.loads((out / "feed.json").read_text(encoding="utf-8"))["items"]
    port = json.loads((out / "portfolio.json").read_text(encoding="utf-8"))
    assert meta["errors"] == []
    assert meta["filter_stats"]["unexplained_moves"] >= 1
    tiers = {it["id"]: it["tier"] for it in feed}
    by_head = {it["headline"][:30]: it for it in feed}
    # results are promise-tier with a computed card; their companions are buried
    res = [it for it in feed if it["category"] == "results" and it["subtype"] == "financials"]
    assert res and all(it["tier"] == "promise" and it["card"]["ok"] for it in res)
    assert all(tiers[it["id"]] == "routine" for it in feed if it["subtype"] in ("companion", "deck", "intimation"))
    # a filing about a quietly dropped promise is linked to it
    halol = next(it for it in feed if "Halol" in it["headline"])
    assert halol["promise_links"][0]["promise_id"] == "NWCABLE-26Q2-3"
    # CFO change carries the profile from the filing
    cfo = next(it for it in feed if "Meera" in it["headline"])
    assert cfo["card"]["changes"][0]["background"]
    assert "web_background" not in cfo["card"]["changes"][0]          # the filing's own profile wins
    director = next(c for c in cfo["card"]["changes"] if c["name"] == "Kavita Menon")
    assert director["web_background"]["sources"][0]["url"].startswith("https://")
    assert "web_background" not in next(c for c in cfo["card"]["changes"] if c["action"] == "resigned")
    # ledgers: management's 'delivered' contradicted by exchange data
    nw = json.loads((out / "companies" / "NWCABLE.json").read_text(encoding="utf-8"))["ledger"]
    p = next(p for p in nw["promises"] if p["id"] == "NWCABLE-26Q2-1")
    assert p["status"] == "missed" and p["contradiction"]
    assert any(c["symbol"] == "NWCABLE" and c["recent"] for c in port["companies"])
    # annual fundamentals, business snapshot, bull and bear
    nwc = json.loads((out / "companies" / "NWCABLE.json").read_text())
    assert nwc["fundamentals"]["trajectory"]["rev_cagr_5y"] and nwc["fundamentals"]["cash"]["conversion"]
    assert nwc["business"]["segments"][0]["name"] == "Wires & cables" and nwc["business"]["year"] == "FY26"
    assert len(nwc["ledger"]["bull"]) == 3 and len(nwc["ledger"]["bear"]) == 3
    assert "78%" in " ".join(nwc["ledger"]["bear"])          # bear case grounded in the computed cash conversion
    # every model call was routed and metered
    assert set(meta["usage_last_run"]["calls"]) <= {"gemini-3.5-flash-lite", "gemini-3.8-flash"}
