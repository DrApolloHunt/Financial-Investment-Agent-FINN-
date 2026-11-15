"""Replays the app's Research flow against a deployed FINN, step by step, with timings.

    python dev/smoke_live.py https://financial-investment-agent-finn.vercel.app ASIANPAINT

Exit code 0 when a ledger was built; 1 otherwise. Uses the deployment's own model key.
"""
from __future__ import annotations

import sys
import time

import requests


def call(base: str, path: str, body: dict | None = None, timeout: int = 300):
    t0 = time.time()
    r = requests.post(base + path, json=body, timeout=timeout) if body is not None else requests.get(base + path, timeout=timeout)
    took = time.time() - t0
    try:
        data = r.json()
    except ValueError:
        data = {"error": r.text[:300]}
    return r.status_code, data, took


def main(base: str, sym: str) -> int:
    base = base.rstrip("/")
    code, co, took = call(base, f"/api/company?t={sym}")
    print(f"company      {code}  {took:5.1f}s  {co.get('name') or co.get('error')}  "
          f"transcripts={len(co.get('transcripts') or [])} annual_reports={len(co.get('annual_reports') or [])} "
          f"fundamentals={'yes' if (co.get('fundamentals') or {}).get('trajectory') else 'no'}")
    if code != 200:
        return 1
    state = None
    for t in reversed(co.get("transcripts") or []):
        code, r, took = call(base, "/api/ledger_step", {"state": state, "symbol": co["symbol"], "name": co["name"],
                                                         "quarter": t["quarter"], "url": t["url"]})
        ok = code == 200 and "state" in r
        print(f"ledger_step  {code}  {took:5.1f}s  {t['quarter']}  "
              + (f"found={r.get('found')} updated={r.get('updated')}" if ok else str(r.get('error'))[:200]))
        if ok:
            state = r["state"]
    if not state:
        print("FAIL: no transcript could be read")
        return 1
    business = None
    if co.get("annual_reports"):
        code, r, took = call(base, "/api/business", {"symbol": co["symbol"]})
        print(f"business     {code}  {took:5.1f}s  " + (str(r.get("what_it_does"))[:120] if code == 200 else str(r.get("error"))[:200]))
        business = r if code == 200 else None
    code, L, took = call(base, "/api/ledger_finalize", {"state": state, "quarters": co.get("quarters"),
                                                          "latest": co.get("latest_quarter"),
                                                          "fundamentals": co.get("fundamentals"), "business": business})
    if code != 200:
        print(f"finalize     {code}  {took:5.1f}s  {str(L.get('error'))[:200]}")
        return 1
    print(f"finalize     {code}  {took:5.1f}s  promises={len(L.get('promises') or [])} counts={L.get('counts')} "
          f"model={L.get('verdict_model')} bull={len(L.get('bull') or [])} bear={len(L.get('bear') or [])}")
    print("credibility:", (L.get("credibility") or "")[:300])
    for b in (L.get("bull") or [])[:1] + (L.get("bear") or [])[:1]:
        print("  -", b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
