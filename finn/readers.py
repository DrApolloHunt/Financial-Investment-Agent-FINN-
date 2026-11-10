"""Model readers for single exchange filings (push side).

Each reader: download the filing PDF once, ask the cheap reading model for
structured fields, cache by (task, attachment URL, prompt version).
Arithmetic and judgement about importance stay in code.
"""
from __future__ import annotations

from typing import Optional

from . import cache, gemini
from .periods import quarter_label
from .sources.exchanges import download_attachment

V_RESULTS = "r3"
V_PERSON = "p2"
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
Do not compute anything. Leave a field null if it is not printed. If this is not a results document, set is_results_document=false."""


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
    data, model = gemini.generate_json("read_pdf", [gemini.pdf_part(_pdf(url)), {"text": RESULTS_PROMPT}], RESULTS_SCHEMA)
    if not data.get("is_results_document"):
        data = {"is_results_document": False}
    else:
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
