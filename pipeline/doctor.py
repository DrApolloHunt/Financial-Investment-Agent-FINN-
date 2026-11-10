"""Day-1 check: can this machine reach every data source, and do the parsers
understand what comes back? Run this before anything else:

    python -m pipeline.doctor            # checks INFY and one portfolio name
    python -m pipeline.doctor DIXON      # or a symbol of your choice

Raw responses are saved to dev/samples/ so parser problems can be fixed from
real pages. Exit code 1 if a source the demo depends on is unreachable.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finn import gemini, http  # noqa: E402
from finn.sources import exchanges, prices, screener  # noqa: E402

SAMPLES = ROOT / "dev" / "samples"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, critical: bool = True):
    def wrap(fn):
        try:
            detail = fn()
            RESULTS.append((name, True, detail))
            print(f"  PASS  {name}: {detail}")
        except Exception as e:
            RESULTS.append((name, not critical, f"{type(e).__name__}: {e}"))
            print(f"  {'FAIL' if critical else 'WARN'}  {name}: {type(e).__name__}: {str(e)[:200]}")
        return fn
    return wrap


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "INFY").upper()
    SAMPLES.mkdir(parents=True, exist_ok=True)
    ctx: dict = {}
    print(f"FINN doctor — {sym}\n")

    @check("screener.in company page")
    def _():
        r = http.get(screener.BASE.format(sym=sym, variant="consolidated/"), expect="html")
        (SAMPLES / f"screener_{sym}.html").write_text(r.text, encoding="utf-8")
        co = screener.parse_company_html(r.text, sym)
        ctx["co"] = co
        q, t = co["quarters"], co["transcripts"]
        if not q["periods"]:
            raise RuntimeError("page fetched but quarterly table not parsed (sample saved)")
        return (f"{co['name']} | BSE {co['bse_code']} | {len(q['periods'])} quarters "
                f"({q['periods'][0]}..{q['periods'][-1]}) | rows {sorted(q['rows'])} | "
                f"{len(t)} transcripts | {len(co['annual_reports'])} annual reports")

    @check("transcript PDF download")
    def _():
        t = (ctx.get("co") or {}).get("transcripts") or []
        if not t:
            raise RuntimeError("no transcript links parsed")
        b = exchanges.download_attachment(t[0]["url"])
        return f"{t[0]['quarter']} {len(b)//1024} KB"

    end = dt.date.today()
    start = end - dt.timedelta(days=30)

    @check("BSE announcements", critical=False)
    def _():
        code = (ctx.get("co") or {}).get("bse_code")
        if not code:
            raise RuntimeError("no BSE code (screener step failed)")
        items = exchanges.bse_announcements(code, sym, start, end)
        (SAMPLES / f"bse_{sym}.json").write_text(json.dumps(items[:30], indent=1), encoding="utf-8")
        ctx["ann"] = items
        return f"{len(items)} filings in 30 days; latest: {items[0]['headline'][:70] if items else '-'}"

    @check("NSE announcements (fallback)", critical=False)
    def _():
        items = exchanges.nse_announcements(sym, start, end)
        (SAMPLES / f"nse_{sym}.json").write_text(json.dumps(items[:30], indent=1), encoding="utf-8")
        ctx.setdefault("ann", items)
        return f"{len(items)} filings in 30 days"

    @check("filings from at least one exchange")
    def _():
        if ctx.get("ann") is None:
            raise RuntimeError("neither BSE nor NSE returned filings")
        return f"{len(ctx['ann'])} filings; the pipeline uses BSE when it answers, otherwise NSE"

    @check("filing attachment download", critical=False)
    def _():
        att = next((a["attachment"] for a in ctx.get("ann", []) if a.get("attachment")), None)
        if not att:
            raise RuntimeError("no attachment links")
        return f"{len(exchanges.download_attachment(att))//1024} KB"

    @check("Yahoo end-of-day prices")
    def _():
        px = prices.daily(sym, "3mo")
        return f"{len(px)} days, last {px[-1]['d']} close {px[-1]['c']} vol {px[-1]['v']}"

    @check("Gemini key and models")
    def _():
        key = gemini.api_key()
        if "paste" in key.lower() or len(key) < 20:
            raise RuntimeError("GEMINI_API_KEY is still a placeholder: paste the real key from aistudio.google.com/apikey")
        models = set(gemini.list_models())
        missing = {t: [m for m in gemini.route(t) if m not in models] for t in gemini.ROUTES}
        missing = {t: m for t, m in missing.items() if m}
        usable = {t: [m for m in gemini.route(t) if m in models] for t in gemini.ROUTES}
        dead = [t for t, m in usable.items() if not m]
        if dead:
            raise RuntimeError(f"no available model for {dead}; available flash models: "
                               f"{sorted(m for m in models if 'flash' in m)[:12]}  (set FINN_MODEL_<TASK>)")
        return f"routes OK; models not found (will be skipped): {missing or 'none'}"

    @check("Gemini JSON call (Flash-Lite)")
    def _():
        data, model = gemini.generate_json("classify", [{"text": 'Return {"ok": true}'}],
                                           {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}})
        return f"{model} -> {data}"

    print()
    failed = [n for n, ok, _ in RESULTS if not ok]
    if failed:
        print("Blocking problems:", ", ".join(failed))
        print(f"Raw samples saved in {SAMPLES} — send them over if a parser needs fixing.")
        sys.exit(1)
    print("All critical sources reachable. Next: python -m pipeline.run --mode full --only", sym)


if __name__ == "__main__":
    main()
