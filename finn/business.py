"""Business snapshot from the latest annual report: what the company does,
its segments and revenue mix.

Annual reports run to hundreds of pages, mostly financial statements and
governance boilerplate. FINN reads the text of the front half locally, keeps
the pages that talk about the business (segments, products, revenue mix,
management discussion), and sends only those to the cheap model. One call per
report, cached forever.
"""
from __future__ import annotations

import io
import re
import time
from typing import Optional

from . import cache, gemini
from .sources.exchanges import download_attachment

V_BUSINESS = "b1"
MAX_PAGES_SCANNED = 160
MAX_SCAN_SECONDS = 40
KEEP_PAGES = 14
MAX_CHARS = 60_000

KEYWORDS = {
    "segment": 4, "revenue mix": 5, "business overview": 5, "our business": 4, "who we are": 4,
    "management discussion": 3, "products": 2, "brands": 2, "customers": 2, "market share": 3,
    "geograph": 2, "export": 2, "domestic": 1, "manufactur": 1, "plants": 1, "capacity": 1,
    "portfolio": 1, "% of revenue": 4, "share of revenue": 4, "contribution": 2,
}

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "what_it_does": {"type": "STRING", "description": "≤45 words, plain English: what the company sells, to whom, how it makes money"},
        "segments": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"},
                           "share_pct": {"type": "NUMBER", "nullable": True},
                           "revenue_crore": {"type": "NUMBER", "nullable": True}},
            "required": ["name"]}},
        "mix_basis": {"type": "STRING", "description": "e.g. 'by business segment, FY26' or 'by geography, FY26'"},
        "other_facts": {"type": "ARRAY", "items": {"type": "STRING"},
                        "description": "up to 3 short facts with numbers: plants, exports share, customers, store count"},
    },
    "required": ["what_it_does", "segments"],
}

PROMPT = """These are pages from {name}'s annual report ({year}). Using ONLY these pages:
1) what_it_does: what the company sells, to whom, and how it makes money (≤45 words, plain English).
2) segments: its business segments (or, if segments are not reported, its revenue by geography or product line),
   with each one's share of revenue in % where the pages state or allow computing it. At most 6. Leave a share null
   rather than guessing.
3) other_facts: up to 3 short, specific facts with numbers (plants, export share, customers, stores).
Do not use outside knowledge of the company.

PAGES:
{pages}"""


def pick_pages(pdf_bytes: bytes) -> tuple[str, list[int]]:
    """Text of the pages most about the business (local, no model)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    t0, scored = time.time(), []
    for i, page in enumerate(reader.pages[:MAX_PAGES_SCANNED]):
        if time.time() - t0 > MAX_SCAN_SECONDS:
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        low = text.lower()
        score = sum(w * low.count(k) for k, w in KEYWORDS.items())
        if "independent auditor" in low or "notes to the financial statements" in low or "corporate governance" in low:
            score *= 0.2
        if len(text) > 400:
            scored.append((score, i, text))
    best = sorted(scored, reverse=True)[:KEEP_PAGES]
    best.sort(key=lambda t: t[1])
    out, used, n = [], [], 0
    for _, i, text in best:
        chunk = re.sub(r"[ \t]+", " ", text)
        if n + len(chunk) > MAX_CHARS:
            break
        out.append(f"--- page {i + 1} ---\n{chunk}")
        used.append(i + 1)
        n += len(chunk)
    return "\n".join(out), used


def year_of(label: str) -> str:
    m = re.search(r"(20\d{2})", label or "")
    return f"FY{int(m.group(1)) % 100:02d}" if m else ""


def read_business(name: str, url: str, label: str = "") -> Optional[dict]:
    key = cache.key_for("business", url, V_BUSINESS)
    hit = cache.get(key)
    if hit is not None:
        return hit
    year = year_of(label)
    text, pages = pick_pages(download_attachment(url))
    if not text:
        return None
    data, model = gemini.generate_json("read_pdf", [{"text": PROMPT.format(name=name, year=year or "latest", pages=text)}], SCHEMA)
    segs = [g for g in (data.get("segments") or []) if (g.get("name") or "").strip()][:6]
    total = sum(g.get("share_pct") or 0 for g in segs)
    if total > 105:  # shares that cannot be shares: keep names, drop numbers
        for g in segs:
            g["share_pct"] = None
    segs.sort(key=lambda g: -(g.get("share_pct") or 0))
    out = {"what_it_does": (data.get("what_it_does") or "").strip()[:400], "segments": segs,
           "mix_basis": (data.get("mix_basis") or "").strip()[:80],
           "other_facts": [f.strip()[:160] for f in (data.get("other_facts") or []) if f.strip()][:3],
           "year": year, "url": url, "pages": pages, "_model": model}
    cache.put(key, out)
    return out


def latest_report(annual_reports: list[dict]) -> Optional[dict]:
    """screener lists newest first; prefer entries that name a financial year."""
    for ar in annual_reports or []:
        if ar.get("url", "").startswith("http") and re.search(r"20\d{2}", ar.get("label", "")):
            return ar
    return (annual_reports or [None])[0]
