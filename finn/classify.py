"""Classify exchange filings into the reference categories.

Rules first: exchange category labels plus headline wording settle most filings
with no model call. Only filings the rules cannot place go to a model, in one
batched call per run.

Each result: {category, subtype, confidence: high|low, rule}
`subtype` lets routine variants of an important category stay buried, e.g. a
results *intimation* (a date notice) versus the results themselves.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CATS = json.loads((Path(__file__).resolve().parent.parent / "config" / "categories.json").read_text(encoding="utf-8"))
CATEGORY_IDS = [c["id"] for c in CATS["categories"]]
ROUTINE_SUBTYPES = CATS["routine_subtypes"]

TOP_ROLES = r"(chief executive|\bceo\b|chief financial|\bcfo\b|managing director|\bm\.?d\.?\b|whole[- ]?time director|executive director|chair(man|person)|chief operating|\bcoo\b|president)"
BOARD_ROLES = r"(independent director|non[- ]executive|nominee director|additional director|\bdirector\b)"


def _has(rx: str, text: str) -> bool:
    return re.search(rx, text) is not None


RULES: list[tuple[str, str, str]] = [
    # (category, subtype, regex) — first match wins; order encodes precedence
    ("unclassified", "trading_window", r"trading window"),
    ("unclassified", "auditor", r"(statutory|secretarial|internal|cost) auditor|appointment of auditor"),
    ("unclassified", "esop", r"\besop|\besos|\besps|employee stock|stock option"),
    ("earnings_call", "transcript", r"transcript|audio recording|recording of (the )?(earnings|conference|analyst)|earnings call|conference call|con\.? ?call|concall"),
    ("results", "deck", r"investor presentation|earnings presentation|results presentation"),
    ("results", "companion", r"(press|media) release.*(financial )?results?|results?.*(press|media) release"),
    ("investor_meetings", "meeting", r"analyst|institutional investor|investor meet|investors? meeting|one[- ]on[- ]one|investor conference"),
    ("pledging", "pledge", r"pledge|encumbrance"),
    ("credit_rating", "rating", r"credit rating|\brating(s)?\b.*(crisil|icra|care|india ratings|fitch|moody|s&p|acuite|brickwork)|(crisil|icra|care ratings|india ratings|acuite)"),
    ("results", "intimation", r"(board meeting intimation|intimation of (the )?board meeting|prior intimation|to consider and approve).*(result|financial)|(result|financial).*(board meeting intimation|prior intimation)"),
    ("results", "ad", r"(newspaper|publication|advertisement).*(result|financial)|(result|financial).*(newspaper|publication|advertisement)"),
    ("results", "financials", r"financial results?|quarterly results|unaudited.*results|audited.*results|results for the (quarter|period|year)|integrated filing.*financ|financial result updates"),
    ("insider_trading", "sast", r"\bsast\b|insider trading|takeover regulation|regulation 7\s*\(2\)|reg(ulation)?\.?\s*29|disclosure.*(acquisition|disposal|sale) of shares"),
    ("bonus_split", "corporate_action", r"\bbonus\b|stock split|sub[- ]?division|split of (equity )?shares"),
    ("M&A", "deal", r"acqui|merger|amalgamation|demerger|scheme of arrangement|joint venture|\bjv\b|stake (sale|purchase)|divest|incorporation of .*subsidiary|investment in .*subsidiary|wholly[- ]owned subsidiary"),
    ("fund_raise", "raise", r"rights issue|\bqip\b|qualified institution|preferential (issue|allotment)|buy[- ]?back|commercial paper|non[- ]convertible debenture|\bncds?\b|fund[- ]?rais|raising of funds|issue of (bonds|debentures)"),
    ("management_change", "change", r"change in (directors?|management|key managerial|directorate|kmp)|appoint|resign|cessation|retire|re-?designat|key managerial"),
    ("litigation", "legal", r"litigation|lawsuit|order passed|penalt|\bfine\b|show cause|tax demand|demand order|\bgst\b|income[- ]tax|enforcement|sebi order|nclt|insolvency|tribunal|court|arbitration|action\(s\) initiated|regulatory action"),
    ("postal_ballot", "ballot", r"postal ballot|e-?voting"),
    ("agm_egm", "meeting", r"\bagm\b|\begm\b|annual general meeting|extra[- ]?ordinary general meeting|general meeting|voting results|scrutini[sz]er|book closure"),
    ("dividend", "dividend", r"dividend|record date"),
    ("capex", "capacity", r"\bcapex\b|capital expenditure|capacity expansion|expansion of capacity|new plant|greenfield|brownfield|commission(ing|ed)|commercial production|setting up (a )?(new )?(plant|facility|unit)"),
    ("press_release", "clarification_routine", r"spurt in (volume|price)|clarification.*(movement|volume|price)|price movement"),
    ("press_release", "news", r"press release|media release|bagged|order|contract|award|launch|partnership|collaborat|\bmou\b|agreement|clarification|news item|update on"),
    ("unclassified", "compliance", r"certificate|compliance|regulation 74|reg\.? ?74|esg|brsr|sustainability|newspaper|share certificate|duplicate|reconciliation of share capital|registrar|investor complaints|corporate governance|secretarial|intimation under regulation|shareholding pattern|loss of share|change in address|website"),
]


def _mgmt_subtype(text: str) -> str:
    if _has(TOP_ROLES, text):
        return "top"
    if _has(r"company secretary|compliance officer|registrar|share transfer agent|auditor", text):
        return "other"
    if _has(BOARD_ROLES, text):
        return "board"
    return "other"


def _rating_subtype(text: str) -> str:
    if _has(r"downgrad|negative|watch", text):
        return "downgrade"
    if _has(r"upgrad|positive", text):
        return "upgrade"
    if _has(r"reaffirm|re-affirm|retain|unchanged", text):
        return "reaffirmed"
    return "assigned"


def classify(item: dict) -> dict:
    text = " | ".join([item.get("raw_category", ""), item.get("raw_subcategory", ""),
                       item.get("headline", ""), item.get("detail", "")]).lower()
    for cat, sub, rx in RULES:
        if _has(rx, text):
            if cat == "management_change":
                sub = _mgmt_subtype(text)
            elif cat == "credit_rating":
                sub = _rating_subtype(text)
            elif cat == "results" and sub == "financials" and _has(r"intimation|to consider", text) and not _has(r"outcome", text):
                sub = "intimation"
            return {"category": cat, "subtype": sub, "confidence": "high", "rule": rx[:40]}
    return {"category": "unclassified", "subtype": "unknown", "confidence": "low", "rule": None}


def is_routine(category: str, subtype: str) -> bool:
    return subtype in ROUTINE_SUBTYPES.get(category, [])


# ---- model fallback for filings the rules could not place -----------------

BATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"id": {"type": "STRING"},
                       "category": {"type": "STRING", "enum": CATEGORY_IDS}},
        "required": ["id", "category"]}}},
    "required": ["items"],
}


def classify_batch_with_model(items: list[dict]) -> dict[str, str]:
    """One call for up to ~40 unplaced headlines. Returns {id: category}."""
    from . import gemini
    if not items:
        return {}
    cats = "\n".join(f"- {c['id']}: {c['desc']}" for c in CATS["categories"])
    lines = "\n".join(f"{it['id']}\t{it.get('raw_category','')}\t{it.get('headline','')[:200]}" for it in items[:40])
    prompt = (f"Classify each Indian stock-exchange filing into exactly one category.\n"
              f"Categories:\n{cats}\n\nFilings (id<TAB>exchange label<TAB>headline):\n{lines}")
    data, _ = gemini.generate_json("classify", [{"text": prompt}], BATCH_SCHEMA)
    return {d["id"]: d["category"] for d in (data or {}).get("items", []) if d.get("category") in CATEGORY_IDS}
