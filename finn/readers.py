"""Model readers for single exchange filings (push side).

Each reader: download the filing PDF once, ask the cheap reading model for
structured fields, cache by (task, attachment URL, prompt version).
Arithmetic and judgement about importance stay in code.
"""
from __future__ import annotations

import re
from typing import Optional

from . import cache, gemini
from .periods import quarter_label
from .sources.exchanges import download_attachment

V_RESULTS = "r4"
V_PERSON = "p2"
V_WEB_BIO = "w1"
V_FILING = "f3"

N = {"type": "NUMBER", "nullable": True}

RESULTS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_results_document": {"type": "BOOLEAN"},
        "basis": {"type": "STRING", "enum": ["consolidated", "standalone"]},
        "unit": {"type": "STRING", "description": "unit of the figures: crore, lakh, million, thousand or rupees"},
        "is_lender": {"type": "BOOLEAN", "description": "true for banks and NBFCs"},
        "quarter_end_date": {"type": "STRING", "description": "YYYY-MM-DD of the latest quarter reported"},
        "periods": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "column_heading": {"type": "STRING"},
                "role": {"type": "STRING", "enum": ["current", "previous_quarter", "year_ago_quarter", "other"]},
                "revenue_from_operations": N, "other_income": N, "total_expenses": N,
                "finance_costs": N, "depreciation": N, "profit_before_exceptional_and_tax": N,
                "pbt": N, "tax": N, "pat": N, "pat_attributable_to_owners": N,
                "operating_profit_before_provisions": N, "provisions": N,
            },
            "required": ["role"]}},
        "notes": {"type": "STRING", "description": "≤25 words on one-offs or exceptional items, else empty"},
    },
    "required": ["is_results_document", "periods"],
}

RESULTS_PROMPT = """You are reading an Indian listed company's quarterly financial results filing.
Extract line items exactly as printed, for three quarter columns:
- role=current: the latest quarter
- role=previous_quarter: the immediately preceding quarter
- role=year_ago_quarter: the same quarter one year earlier
Ignore half-year and full-year columns. Prefer the CONSOLIDATED statement if present, else standalone.
Use the document's own numbers and state the unit printed in the header (crore, lakh, million...).
For banks/NBFCs set is_lender=true; revenue_from_operations = interest earned / revenue from operations,
and fill operating_profit_before_provisions and provisions if printed.
Read these lines carefully; they are often missed: "Finance costs", "Depreciation and amortisation expense",
"Total expenses", "Profit before exceptional items and tax", "Profit before tax", "Net profit for the period"
and "attributable to owners of the parent". Use the column headings to match each number to its quarter.
Do not compute anything. Leave a field null if it is not printed. If this is not a results document, set is_results_document=false."""

FILL_PROMPT = """The text below is from an Indian listed company's quarterly results filing. Earlier extraction missed
some line items. For the three quarter columns (current quarter, previous quarter, same quarter last year) of the
{basis} statement, fill in: {missing}. Copy numbers exactly as printed, in the document's own unit ({unit}).
Leave null anything you cannot find. Do not compute.

TEXT:
{text}"""

NEEDED = ("revenue_from_operations", "total_expenses", "finance_costs", "depreciation", "pbt", "pat")


def _missing(data: dict) -> list[str]:
    cur = next((p for p in data.get("periods") or [] if p.get("role") == "current"), None)
    if not cur:
        return list(NEEDED)
    need = [k for k in NEEDED if cur.get(k) is None]
    if data.get("is_lender"):
        need = [k for k in need if k not in ("total_expenses", "depreciation", "finance_costs")]
    return need


def _results_text(pdf_bytes: bytes, max_chars: int = 40_000) -> str:
    """Text of the pages that hold the statement of profit and loss."""
    import io
    from pypdf import PdfReader
    pages = []
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages[:30]:
        try:
            t = page.extract_text() or ""
        except Exception:
            continue
        low = t.lower()
        if ("finance cost" in low or "depreciation" in low) and ("profit" in low or "revenue" in low):
            pages.append(t)
    return "\n---\n".join(pages)[:max_chars]


def _fill_missing(data: dict, pdf_bytes: bytes) -> dict:
    """Second, focused pass on the statement pages' text for lines the first pass left blank."""
    need = _missing(data)
    if not need:
        return data
    text = _results_text(pdf_bytes)
    if not text:
        return data
    prompt = FILL_PROMPT.format(basis=data.get("basis") or "consolidated", missing=", ".join(need),
                                unit=data.get("unit") or "as printed", text=text)
    more, model = gemini.generate_json("read_pdf", [{"text": prompt}], RESULTS_SCHEMA)
    by_role = {p.get("role"): p for p in more.get("periods") or []}
    for p in data.get("periods") or []:
        extra = by_role.get(p.get("role")) or {}
        for k in NEEDED + ("other_income", "pat_attributable_to_owners", "profit_before_exceptional_and_tax"):
            if p.get(k) is None and extra.get(k) is not None:
                p[k] = extra[k]
    data["_filled_by"] = model
    return data


PERSON_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "changes": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "role": {"type": "STRING"},
                "action": {"type": "STRING", "enum": ["appointed", "resigned", "retired", "redesignated", "ceased", "other"]},
                "level": {"type": "STRING", "enum": ["top", "board", "other"],
                          "description": "top = CEO/CFO/MD/whole-time or executive director/chair/COO"},
                "effective": {"type": "STRING"},
                "background": {"type": "STRING", "description": "≤45 words from the filing's profile: prior roles, years, qualifications"},
                "previous_employers": {"type": "ARRAY", "items": {"type": "STRING"}},
                "reason": {"type": "STRING", "description": "stated reason for leaving, if any, ≤15 words"},
            },
            "required": ["name", "role", "action", "level"]}},
    },
    "required": ["changes"],
}

PERSON_PROMPT = """This is an Indian stock-exchange disclosure about a change in directors or key managerial personnel.
SEBI rules require a brief profile of any person appointed; use ONLY what this document says.
List each person whose position changes. For background, summarise the profile in the filing (prior roles,
employers, years of experience, qualifications). If no profile is given, leave background empty."""


FILING_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "one_line": {"type": "STRING", "description": "≤18 words: what happened, with the key number if any"},
        "importance": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "why": {"type": "STRING", "description": "≤14 words: why an investor would or would not care"},
        "promise_links": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "promise_id": {"type": "STRING"},
                "effect": {"type": "STRING", "enum": ["supports", "undermines", "updates"]},
                "note": {"type": "STRING", "description": "≤16 words"},
            },
            "required": ["promise_id", "effect", "note"]}},
    },
    "required": ["one_line", "importance", "why", "promise_links"],
}

FILING_PROMPT = """You are triaging a stock-exchange filing for a busy, high-conviction investor.
Company: {name}. Exchange label: {label}. Headline: {headline}

Management has made these open promises (id: promise):
{promises}

1) one_line: what this filing actually says, plainly, with the key number.
2) importance: high only if it could change revenue, margins, balance sheet, control or credibility; low for routine paperwork.
3) promise_links: list ONLY promises this filing directly bears on (e.g. a plant commissioning for a capacity promise,
   an order win for an order-inflow target). Most filings bear on none: return an empty list then.
Use only this document."""


def _pdf(url: str) -> bytes:
    return download_attachment(url)


def read_results(url: str) -> Optional[dict]:
    key = cache.key_for("results", url, V_RESULTS)
    hit = cache.get(key)
    if hit is not None:
        return hit
    pdf = _pdf(url)
    data, model = gemini.generate_json("read_pdf", [gemini.pdf_part(pdf), {"text": RESULTS_PROMPT}], RESULTS_SCHEMA)
    if not data.get("is_results_document"):
        data = {"is_results_document": False}
    else:
        try:
            data = _fill_missing(data, pdf)
        except Exception:
            pass  # the exchange-data check downstream still guards the card
        d = data.get("quarter_end_date") or ""
        if len(d) >= 7:
            y, m = int(d[:4]), int(d[5:7])
            data["quarter"] = quarter_label(f"{['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m]} {y}")
    data["_model"] = model
    cache.put(key, data)
    return data


def read_person(url: str) -> Optional[dict]:
    key = cache.key_for("person", url, V_PERSON)
    hit = cache.get(key)
    if hit is not None:
        return hit
    data, model = gemini.generate_json("read_pdf", [gemini.pdf_part(_pdf(url)), {"text": PERSON_PROMPT}], PERSON_SCHEMA)
    data["_model"] = model
    cache.put(key, data)
    return data


def read_filing(url: str, name: str, label: str, headline: str, promises: list[dict]) -> dict:
    ids = ",".join(sorted(p["id"] for p in promises))
    key = cache.key_for("filing", f"{url}|{ids}", V_FILING)
    hit = cache.get(key)
    if hit is not None:
        return hit
    plist = "\n".join(f"{p['id']}: {p['statement']}" for p in promises) or "(none recorded)"
    prompt = FILING_PROMPT.format(name=name, label=label, headline=headline, promises=plist)
    data, model = gemini.generate_json("read_pdf", [gemini.pdf_part(_pdf(url)), {"text": prompt}], FILING_SCHEMA)
    valid = {p["id"] for p in promises}
    data["promise_links"] = [l for l in data.get("promise_links") or [] if l.get("promise_id") in valid]
    data["_model"] = model
    cache.put(key, data)
    return data


WEB_BIO_PROMPT = """Search the web for the professional background of {name}, who was {action} as {role} of
{company} (an Indian listed company){when}. Answer in at most 45 words: prior employers and roles, years of
experience, and qualifications. Only describe this specific person at this company. If the sources do not
clearly refer to this person, reply with exactly UNKNOWN. Plain text, no preamble, no markdown."""


_WEB_BIO_ERR = [""]


def web_bio_error() -> str:
    """Why the last web_bio call returned None."""
    return _WEB_BIO_ERR[0] or "none"


def web_bio(name: str, role: str, company: str, action: str = "appointed", effective: str = "") -> Optional[dict]:
    """Best-effort background from a grounded web search, for people whose filing carries no profile.
    Returns {"text", "sources", "model"} or None. Never raises."""
    key = cache.key_for("web_bio", f"{company}|{name}|{role}", V_WEB_BIO)
    hit = cache.get(key)
    if hit is not None:
        _WEB_BIO_ERR[0] = "cached: no confident match earlier"
        return hit or None
    prompt = WEB_BIO_PROMPT.format(name=name, role=role, company=company, action=action,
                                   when=f", effective {effective}" if effective else "")
    try:
        text, model, sources = gemini.search_text("web_bio", prompt)
    except gemini.NoKey:
        _WEB_BIO_ERR[0] = "no API key"
        return None
    except gemini.GeminiError as e:
        _WEB_BIO_ERR[0] = f"search call failed: {str(e)[:200]}"
        return None  # not cached: grounding may be available on a later run
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text).strip().strip('"')
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    words = text.split()
    if not sources:
        _WEB_BIO_ERR[0] = "the answer came back without search sources"
        return None  # not cached: the search may simply not have run this time
    if "UNKNOWN" in text.upper()[:20] or len(words) < 6:
        _WEB_BIO_ERR[0] = "model was not confident it was the same person"
        cache.put(key, {})
        return None
    if len(words) > 60:
        text = " ".join(words[:60]).rstrip(",;") + "…"
    out = {"text": text, "sources": sources, "model": model}
    cache.put(key, out)
    return out
