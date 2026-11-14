"""Screenshot the app at phone size against fictional fixtures (dev only)."""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
OUT = "dev/shots"
shots = [
    ("today", "/?fixtures#/", None),
    ("today-buried", "/?fixtures#/", "[data-win='7d']|[data-bury]"),
    ("today-dates", "/?fixtures#/", "[data-win='custom']"),
    ("ledgers", "/?fixtures#/ledgers", None),
    ("company", "/?fixtures#/c/NWCABLE", ".prow > .b"),
    ("research", "/?fixtures#/research/LOTUSPNT", None),
    ("settings", "/?fixtures#/settings", None),
    ("research-live", "/?fixtures#/research/MERIDIAN", None),
]
with sync_playwright() as p:
    b = p.chromium.launch()
    for scheme in ("light", "dark"):
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme=scheme)
        page = ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        for name, path, click in shots if scheme == "light" else shots[:1] + shots[4:5]:
            page.goto(BASE + path)
            page.wait_for_timeout(2500 if "live" in name else 700)
            for sel in (click.split("|") if click else []):
                page.click(sel)
                page.wait_for_timeout(300)
            page.screenshot(path=f"{OUT}/{name}-{scheme}.png", full_page=True)
            if name in ("today-buried", "today-dates"):
                page.click("[data-win='24h']")
        print(scheme, "errors:", errs or "none")
        ctx.close()
    b.close()
