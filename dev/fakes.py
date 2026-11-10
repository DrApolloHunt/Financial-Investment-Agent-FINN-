"""Fictional companies and a fake model, for development only.

Every name, number and quote here is invented. The fakes stand in for
screener.in, the exchanges, Yahoo and Gemini so the REAL pipeline code can run
end to end offline (integration test) and the UI has data to be designed on.
Nothing here is shipped to or shown by the deployed app.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import random
import re

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# 13 quarter-ends: Sep 2023 (Q2 FY24) .. Sep 2026 (Q2 FY27)
QEND = []
y, m = 2023, 9
for _ in range(13):
    QEND.append((m, y))
    m += 3
    if m > 12:
        m, y = m - 12, y + 1

COMPANIES = {
    "NWCABLE": dict(name="Northwind Cables Ltd", bse="900001", sector="Cables & wires", base=900, g=0.042,
                    m0=14.2, m1=12.2, lender=False),
    "KESTREL": dict(name="Kestrel Software Ltd", bse="900002", sector="IT services", base=5200, g=0.008,
                    m0=21.0, m1=21.3, lender=False),
    "ASTERDEF": dict(name="Aster Defence Systems Ltd", bse="900003", sector="Defence electronics", base=4000, g=0.036,
                     m0=26.8, m1=27.6, lender=False),
    "SAFFRON": dict(name="Saffron Finance Ltd", bse="900004", sector="Consumer lending", base=3000, g=0.055,
                    m0=62.0, m1=60.5, lender=True),
    "ORBITEMS": dict(name="Orbit EMS Ltd", bse="900005", sector="Electronics manufacturing", base=2300, g=0.06,
                     m0=4.6, m1=4.15, lender=False),
    "LOTUSPNT": dict(name="Lotus Paints Ltd", bse="900006", sector="Paints", base=8000, g=0.015,
                     m0=19.5, m1=18.6, lender=False),
    # only reachable through the live research API (no prebuilt file), to exercise that path
    "MERIDIAN": dict(name="Meridian Foods Ltd", bse="900007", sector="Packaged foods", base=1800, g=0.03,
                     m0=14.0, m1=12.4, lender=False),
}

CALL_MONTHS = {"Q2 FY26": "Oct 2025", "Q3 FY26": "Jan 2026", "Q4 FY26": "May 2026",
               "Q1 FY27": "Jul 2026", "Q2 FY27": "Oct 2026"}
CALLS = {s: list(CALL_MONTHS) for s in COMPANIES}
CALLS["ORBITEMS"] = ["Q4 FY26", "Q1 FY27", "Q2 FY27"]


def table(sym: str) -> dict:
    c = COMPANIES[sym]
    season = [0.0, 0.015, 0.05, -0.02]
    rows = {k: [] for k in ("revenue", "expenses", "ebitda", "margin", "other_income", "interest", "depreciation", "pbt", "pat")}
    for i, (mm, yy) in enumerate(QEND):
        rev = c["base"] * (1 + c["g"]) ** i * (1 + season[i % 4])
        mg = c["m0"] + (c["m1"] - c["m0"]) * i / 12
        ebitda = rev * mg / 100
        oth, intr, dep = rev * 0.008, rev * (0.18 if c["lender"] else 0.02), rev * 0.025
        if c["lender"]:
            intr = 0
        pbt = ebitda + oth - intr - dep
        pat = pbt * 0.75
        for k, v in (("revenue", rev), ("expenses", rev - ebitda), ("ebitda", ebitda), ("margin", mg),
                     ("other_income", oth), ("interest", intr), ("depreciation", dep), ("pbt", pbt), ("pat", pat)):
            rows[k].append(round(v, 0) if k != "margin" else round(v, 0))
    return rows


def screener_html(sym: str) -> str:
    c, t = COMPANIES[sym], table(sym)
    labels = {"revenue": "Revenue" if c["lender"] else "Sales", "expenses": "Expenses",
              "ebitda": "Financing Profit" if c["lender"] else "Operating Profit",
              "margin": "Financing Margin %" if c["lender"] else "OPM %", "other_income": "Other Income",
              "interest": "Interest", "depreciation": "Depreciation", "pbt": "Profit before tax", "pat": "Net Profit"}
    head = "".join(f"<th>{MONTHS[m]} {y}</th>" for m, y in QEND)
    body = ""
    for k, lab in labels.items():
        cells = "".join(f"<td>{v:,.0f}{'%' if k == 'margin' else ''}</td>" for v in t[k])
        body += f"<tr><td class='text'>{lab}&nbsp;+</td>{cells}</tr>"
    calls = "".join(
        f"<li><div>{CALL_MONTHS[q]}</div><a class='concall-link' href='https://fake.local/{sym}/{q.replace(' ', '_')}.pdf'>Transcript</a></li>"
        for q in reversed(CALLS[sym]))
    return f"""<html><body><h1>{c['name']}</h1><span>BSE: {c['bse']}</span><span>NSE: {sym}</span>
<section id="quarters"><table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></section>
<div class="documents annual-reports"><ul><li><a href="https://fake.local/{sym}/AR2026.pdf">Financial Year 2026</a></li></ul></div>
<div class="documents concalls"><ul>{calls}</ul></div></body></html>"""


def fetch_company(symbol: str) -> dict:
    from finn.sources.screener import parse_company_html
    if symbol not in COMPANIES:
        from finn.http import FetchError
        raise FetchError(symbol, 404, "not found")
    d = parse_company_html(screener_html(symbol), symbol, f"https://fake.local/{symbol}")
    d["basis"] = "consolidated"
    return d


def trading_days(n: int) -> list[dt.date]:
    out, d = [], dt.datetime.now(IST).date()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(out))


EVENTS = {  # symbol -> {trading days before the latest: (pct_move, volume_multiple)}
    "ORBITEMS": {0: (-7.8, 3.1)},     # explained by the CFO exit filed that morning
    "ASTERDEF": {1: (5.2, 2.6), 0: (-4.6, 2.4)},   # order win explains day 1; day 0 has no filing
    "NWCABLE": {0: (4.4, 2.2)},       # plant starts production
    "SAFFRON": {6: (-5.9, 2.8)},      # nothing filed: unexplained
}


def daily(symbol: str, range_: str = "6mo") -> list[dict]:
    rnd = random.Random(symbol)
    days = trading_days(125)
    px, vbase = 100 + rnd.random() * 1500, 2e5 + rnd.random() * 3e6
    out = []
    ev = EVENTS.get(symbol, {})
    for i, d in enumerate(days):
        k = len(days) - 1 - i
        if k in ev:
            pct, vm = ev[k]
            px *= 1 + pct / 100
            vol = vbase * vm
        else:
            px *= 1 + rnd.gauss(0.0006, 0.012)
            vol = vbase * (0.75 + rnd.random() * 0.5)
        out.append({"d": d.isoformat(), "c": round(px, 2), "v": int(vol)})
    return out


def _ts(day_offset: int, hhmm: str) -> str:
    d = trading_days(day_offset + 1)[0]
    h, m = map(int, hhmm.split(":"))
    t = dt.datetime.combine(d, dt.time(h, m), IST)
    now = dt.datetime.now(IST)
    return min(t, now - dt.timedelta(minutes=12)).replace(microsecond=0).isoformat()


FILINGS = {
    "KESTREL": [(0, "07:40", "Result", "Financial Results", "Unaudited Financial Results for the quarter and half year ended September 30, 2026"),
                (0, "07:45", "Company Update", "Press Release / Media Release", "Press release on financial results Q2 FY27"),
                (0, "07:50", "Result", "", "Investor presentation for Q2 FY27"),
                (1, "17:10", "Company Update", "", "Allotment of equity shares under ESOP 2019"),
                (8, "16:00", "Board Meeting", "Board Meeting Intimation", "Board Meeting Intimation for considering financial results"),
                (3, "18:20", "Others", "", "Compliance certificate under Regulation 74(5) of SEBI (DP) Regulations")],
    "ORBITEMS": [(0, "09:05", "Company Update", "Change in Management", "Appointment of Ms. Meera Raghavan as Chief Financial Officer"),
                 (0, "09:06", "Company Update", "Change in Management", "Resignation of Mr. Anil Joshi as Chief Financial Officer"),
                 (2, "18:00", "Company Update", "", "Analyst / Investor Meet - Intimation"),
                 (2, "18:05", "Company Update", "", "Analyst / Investor Meet - Intimation"),
                 (5, "19:30", "Result", "Financial Results", "Unaudited Financial Results for the quarter ended September 30, 2026")],
    "ASTERDEF": [(1, "11:20", "Company Update", "Award of Order / Receipt of Order", "Receipt of orders worth Rs 3,150 crore from Ministry of Defence"),
                 (3, "17:00", "Company Update", "", "Credit rating reaffirmed by CRISIL at AAA/Stable"),
                 (6, "16:45", "Result", "Financial Results", "Audited Financial Results for the quarter ended 30 September 2026"),
                 (5, "20:00", "Company Update", "", "Transcript of the earnings conference call for Q2 FY27")],
    "NWCABLE": [(0, "10:15", "Company Update", "", "Commencement of commercial production at the Halol wire plant"),
                (2, "08:00", "Others", "", "Copy of newspaper publication of financial results"),
                (3, "17:30", "AGM/EGM", "", "Notice of Postal Ballot"),
                (4, "12:00", "Company Update", "", "Intimation of loss of share certificate"),
                (7, "18:10", "Result", "Financial Results", "Unaudited Financial Results for the quarter ended 30.09.2026")],
    "SAFFRON": [(0, "14:10", "Insider Trading / SAST", "", "Disclosure of release of pledged shares by promoter group"),
                (1, "16:30", "Company Update", "", "Issue of non-convertible debentures on private placement basis Rs 1,000 crore"),
                (4, "17:45", "Result", "Financial Results", "Unaudited Financial Results for quarter ended September 30, 2026"),
                (3, "21:00", "Company Update", "", "Earnings call transcript Q2 FY27")],
}


def announcements(symbol, bse_code, start, end):
    out = []
    for i, (day, hhmm, cat, sub, head) in enumerate(FILINGS.get(symbol, [])):
        out.append({"id": f"FAKE-{symbol}-{i}", "source": "BSE", "symbol": symbol, "ts": _ts(day, hhmm),
                    "headline": head, "detail": "", "raw_category": cat, "raw_subcategory": sub,
                    "attachment": f"https://fake.local/{symbol}/filing{i}.pdf"})
    return out, "BSE"


def download_attachment(url: str) -> bytes:
    return b"%PDF-FAKE|" + url.encode()


# ---- fake model ---------------------------------------------------------------------

def P(statement, quote, theme, metric, basis, lo, hi, unit, horizon, he=None, direction="higher_is_better", hard=True, speaker="CEO"):
    return {"statement": statement, "quote": quote, "speaker": speaker, "theme": theme, "metric": metric, "basis": basis,
            "direction": direction, "target_low": lo, "target_high": hi, "unit": unit, "horizon": horizon,
            "horizon_end": he, "specificity": "hard" if hard else "soft"}


def U(pid, kind, q="", lo=None, hi=None, rep=None, note=""):
    return {"promise_id": pid, "kind": kind, "quote": q, "new_target_low": lo, "new_target_high": hi,
            "reported_value": rep, "note": note}


TRANSCRIPTS = {
    ("NWCABLE", "Q2 FY26"): {"new_promises": [
        P("FY26 revenue growth of 18–20%", "we are confident of 18 to 20 percent topline growth this year", "growth", "revenue_growth", "fy", 18, 20, "%", "FY26"),
        P("EBITDA margin of 13–14% for FY26", "margins should settle in the 13 to 14 percent band", "margin", "ebitda_margin", "fy", 13, 14, "%", "FY26", speaker="CFO"),
        P("Commission the Halol wire plant by Q4 FY26", "Halol will be commissioned by the fourth quarter", "capex", "capacity", "other", None, None, "", "Q4 FY26")],
        "updates": []},
    ("NWCABLE", "Q3 FY26"): {"new_promises": [], "updates": [
        U("NWCABLE-26Q2-1", "reiterated", "we stay with 18 to 20 percent"),
        U("NWCABLE-26Q2-2", "lowered", "copper volatility means 12.5 to 13 percent is more realistic", 12.5, 13),
        U("NWCABLE-26Q2-3", "delayed", "Halol now moves to the first quarter of next year", note="pushed to Q1 FY27")]},
    ("NWCABLE", "Q4 FY26"): {"new_promises": [
        P("FY27 revenue growth of at least 15%", "we would not be satisfied with anything below 15 percent", "growth", "revenue_growth", "fy", 15, None, "%", "FY27"),
        P("Exports at 10% of revenue by FY28", "exports should be a tenth of the business by FY28", "growth", "other", "other", 10, 10, "%", "FY28")],
        "updates": [U("NWCABLE-26Q2-1", "delivered", "we delivered our growth guidance for the year", rep=18)]},
    ("NWCABLE", "Q1 FY27"): {"new_promises": [], "updates": [
        U("NWCABLE-26Q4-1", "reiterated", "15 percent plus remains the floor"),
        U("NWCABLE-26Q4-2", "reiterated", "exports on track for ten percent")]},
    ("NWCABLE", "Q2 FY27"): {"new_promises": [
        P("Working-capital days below 60 by end of FY27", "we will bring working capital under 60 days", "balance_sheet", "other", "other", None, 60, "days", "FY27", direction="lower_is_better", speaker="CFO")],
        "updates": [U("NWCABLE-26Q4-1", "raised", "we now see 17 to 18 percent growth", 17, 18)]},

    ("KESTREL", "Q2 FY26"): {"new_promises": [
        P("FY26 revenue growth of 3–5% in constant currency", "we hold our guidance of 3 to 5 percent in constant currency", "growth", "revenue_growth", "constant_currency", 3, 5, "%", "FY26"),
        P("Operating margin of 20–22% for FY26", "operating margin band of 20 to 22 percent", "margin", "ebitda_margin", "fy", 20, 22, "%", "FY26", speaker="CFO"),
        P("Large-deal wins above $1.5bn every quarter", "large deal TCV should stay above 1.5 billion each quarter", "growth", "order_inflow", "quarter", 1.5, None, "$bn", "every quarter", hard=False)],
        "updates": []},
    ("KESTREL", "Q3 FY26"): {"new_promises": [], "updates": [
        U("KESTREL-26Q2-1", "reiterated"), U("KESTREL-26Q2-2", "reiterated"),
        U("KESTREL-26Q2-3", "delivered", "large deal TCV was 1.7 billion", rep=1.7)]},
    ("KESTREL", "Q4 FY26"): {"new_promises": [
        P("FY27 revenue growth of 3–5% in constant currency", "for FY27 we guide 3 to 5 percent constant currency", "growth", "revenue_growth", "constant_currency", 3, 5, "%", "FY27"),
        P("Operating margin of 20–22% for FY27", "we maintain the 20 to 22 percent margin band", "margin", "ebitda_margin", "fy", 20, 22, "%", "FY27", speaker="CFO")],
        "updates": [U("KESTREL-26Q2-1", "delivered", "full-year constant currency growth of 3.4 percent", rep=3.4),
                    U("KESTREL-26Q2-2", "delivered", "margin for the year was 21.2 percent", rep=21.2)]},
    ("KESTREL", "Q1 FY27"): {"new_promises": [
        P("Hire 5,000 freshers in FY27", "we will onboard about 5,000 freshers this year", "other", "other", "fy", 5000, None, "people", "FY27", hard=False)],
        "updates": [U("KESTREL-26Q4-1", "reiterated"), U("KESTREL-26Q4-2", "reiterated")]},
    ("KESTREL", "Q2 FY27"): {"new_promises": [], "updates": [
        U("KESTREL-26Q4-1", "lowered", "we are revising guidance to 2 to 4 percent", 2, 4, note="discretionary spend weak"),
        U("KESTREL-26Q4-2", "reiterated", "margins remain within 20 to 22")]},

    ("ASTERDEF", "Q2 FY26"): {"new_promises": [
        P("FY26 order inflow of ₹22,000 crore", "we expect order inflows of about 22,000 crore", "growth", "order_inflow", "absolute", 22000, None, "crore", "FY26"),
        P("FY26 revenue growth of 15%", "revenue growth of 15 percent this year", "growth", "revenue_growth", "fy", 15, None, "%", "FY26"),
        P("EBITDA margin of 27–28%", "EBITDA margin in the 27 to 28 percent range", "margin", "ebitda_margin", "fy", 27, 28, "%", "FY26", speaker="Director (Finance)")],
        "updates": []},
    ("ASTERDEF", "Q3 FY26"): {"new_promises": [], "updates": [
        U("ASTERDEF-26Q2-1", "reiterated"), U("ASTERDEF-26Q2-2", "reiterated"), U("ASTERDEF-26Q2-3", "reiterated")]},
    ("ASTERDEF", "Q4 FY26"): {"new_promises": [
        P("FY27 order inflow of ₹25,000 crore", "for FY27 we see inflows of around 25,000 crore", "growth", "order_inflow", "absolute", 25000, None, "crore", "FY27"),
        P("FY27 revenue growth of 15%", "we again target 15 percent growth", "growth", "revenue_growth", "fy", 15, None, "%", "FY27"),
        P("FY27 EBITDA margin of about 27%", "margins around 27 percent", "margin", "ebitda_margin", "fy", 27, 27, "%", "FY27", speaker="Director (Finance)")],
        "updates": [U("ASTERDEF-26Q2-1", "delivered", "order inflow for the year was 23,400 crore", rep=23400),
                    U("ASTERDEF-26Q2-2", "delivered", "we delivered 15 percent growth"),
                    U("ASTERDEF-26Q2-3", "delivered", "EBITDA margin of 27.6 percent", rep=27.6)]},
    ("ASTERDEF", "Q1 FY27"): {"new_promises": [], "updates": [
        U("ASTERDEF-26Q4-1", "reiterated"), U("ASTERDEF-26Q4-2", "reiterated"), U("ASTERDEF-26Q4-3", "reiterated")]},
    ("ASTERDEF", "Q2 FY27"): {"new_promises": [], "updates": [
        U("ASTERDEF-26Q4-1", "reiterated", "H1 inflows of 11,800 crore keep us on course"),
        U("ASTERDEF-26Q4-2", "reiterated"),
        U("ASTERDEF-26Q4-3", "raised", "we now expect 27 to 29 percent", 27, 29)]},

    ("SAFFRON", "Q2 FY26"): {"new_promises": [
        P("AUM growth of 25–27% in FY26", "AUM growth of 25 to 27 percent", "growth", "other", "fy", 25, 27, "%", "FY26"),
        P("Credit cost of 1.8–2.0% in FY26", "credit cost between 1.8 and 2 percent", "balance_sheet", "cost", "fy", 1.8, 2.0, "%", "FY26", direction="lower_is_better", speaker="CFO"),
        P("Net interest margin around 10%", "NIMs should hold around 10 percent", "margin", "other", "fy", 10, 10, "%", "FY26", hard=False)],
        "updates": []},
    ("SAFFRON", "Q3 FY26"): {"new_promises": [], "updates": [
        U("SAFFRON-26Q2-1", "reiterated"), U("SAFFRON-26Q2-2", "reiterated"), U("SAFFRON-26Q2-3", "reiterated")]},
    ("SAFFRON", "Q4 FY26"): {"new_promises": [
        P("AUM growth of 24–26% in FY27", "we guide 24 to 26 percent AUM growth", "growth", "other", "fy", 24, 26, "%", "FY27"),
        P("Credit cost of 1.9–2.1% in FY27", "credit cost of 1.9 to 2.1 percent", "balance_sheet", "cost", "fy", 1.9, 2.1, "%", "FY27", direction="lower_is_better", speaker="CFO")],
        "updates": [U("SAFFRON-26Q2-1", "delivered", "AUM grew 26 percent", rep=26),
                    U("SAFFRON-26Q2-2", "missed", "credit cost came in at 2.2 percent", rep=2.2)]},
    ("SAFFRON", "Q1 FY27"): {"new_promises": [], "updates": [
        U("SAFFRON-26Q4-1", "reiterated"), U("SAFFRON-26Q4-2", "reiterated")]},
    ("SAFFRON", "Q2 FY27"): {"new_promises": [], "updates": [
        U("SAFFRON-26Q4-1", "reiterated", "AUM up 25 percent", rep=25),
        U("SAFFRON-26Q4-2", "raised", "credit cost likely 2.1 to 2.3 percent", 2.1, 2.3)]},

    ("ORBITEMS", "Q4 FY26"): {"new_promises": [
        P("FY27 revenue of ₹14,000 crore", "we target revenue of 14,000 crore in FY27", "growth", "other", "absolute", 14000, None, "crore", "FY27"),
        P("Mobile capacity of 50 million units by Q3 FY27", "50 million unit capacity by the third quarter", "capex", "capacity", "other", 50, None, "million units", "Q3 FY27"),
        P("FY27 EBITDA margin of 4.5–5%", "EBITDA margin of 4.5 to 5 percent", "margin", "ebitda_margin", "fy", 4.5, 5, "%", "FY27", speaker="CFO")],
        "updates": []},
    ("ORBITEMS", "Q1 FY27"): {"new_promises": [], "updates": [
        U("ORBITEMS-26Q4-1", "reiterated"), U("ORBITEMS-26Q4-2", "reiterated"), U("ORBITEMS-26Q4-3", "reiterated")]},
    ("ORBITEMS", "Q2 FY27"): {"new_promises": [], "updates": [
        U("ORBITEMS-26Q4-1", "reiterated", "14,000 crore remains the number"),
        U("ORBITEMS-26Q4-2", "delayed", "capacity now by year end", note="pushed to Q4 FY27"),
        U("ORBITEMS-26Q4-3", "reiterated", "we remain confident of 4.5 percent plus")]},

    ("LOTUSPNT", "Q2 FY26"): {"new_promises": [
        P("Double-digit volume growth in FY26", "we will deliver double digit volume growth", "growth", "volume_growth", "fy", 10, None, "%", "FY26"),
        P("EBITDA margin of 18–20%", "EBITDA margin band of 18 to 20 percent", "margin", "ebitda_margin", "fy", 18, 20, "%", "FY26")],
        "updates": []},
    ("LOTUSPNT", "Q3 FY26"): {"new_promises": [], "updates": [
        U("LOTUSPNT-26Q2-1", "lowered", "high single digit volume growth is more likely", 7, 9),
        U("LOTUSPNT-26Q2-2", "reiterated")]},
    ("LOTUSPNT", "Q4 FY26"): {"new_promises": [
        P("FY27 volume growth in high single digits", "high single digit volume growth for FY27", "growth", "volume_growth", "fy", 7, 9, "%", "FY27")],
        "updates": [U("LOTUSPNT-26Q2-1", "missed", "volume growth was 6 percent", rep=6),
                    U("LOTUSPNT-26Q2-2", "delivered", "margin of 18.4 percent", rep=18.4)]},
    ("LOTUSPNT", "Q1 FY27"): {"new_promises": [], "updates": [U("LOTUSPNT-26Q4-1", "reiterated")]},
    ("LOTUSPNT", "Q2 FY27"): {"new_promises": [], "updates": [U("LOTUSPNT-26Q4-1", "reiterated")]},
}

PEOPLE = {"changes": [
    {"name": "Meera Raghavan", "role": "Chief Financial Officer", "action": "appointed", "level": "top",
     "effective": "11 Nov 2026",
     "background": "Chartered accountant with 22 years in finance; previously CFO of Delta Components and treasury head at a consumer-durables maker.",
     "previous_employers": ["Delta Components", "Brightline Appliances"], "reason": ""},
    {"name": "Anil Joshi", "role": "Chief Financial Officer", "action": "resigned", "level": "top",
     "effective": "10 Nov 2026", "background": "", "previous_employers": [], "reason": "to pursue opportunities outside the company"}]}


def _results(sym: str) -> dict:
    t = table(sym)
    lender = COMPANIES[sym]["lender"]

    def col(i, role):
        rev, eb, fin, dep, oth = t["revenue"][i], t["ebitda"][i], t["interest"][i], t["depreciation"][i], t["other_income"][i]
        d = {"role": role, "revenue_from_operations": rev * 100, "other_income": oth * 100,
             "total_expenses": (rev - eb + fin + dep) * 100, "finance_costs": fin * 100, "depreciation": dep * 100,
             "pbt": t["pbt"][i] * 100, "pat": t["pat"][i] * 100}
        if lender:
            d["operating_profit_before_provisions"] = eb * 100
        return d
    return {"is_results_document": True, "basis": "consolidated", "unit": "lakh", "is_lender": lender,
            "quarter_end_date": "2026-09-30", "periods": [col(12, "current"), col(11, "previous_quarter"), col(8, "year_ago_quarter")],
            "notes": ""}


FILING_SUMMARY = {
    "Receipt of orders": ("Won ₹3,150 crore of defence orders; H2 inflow now needs ~₹10,000 crore more.", "high", "Directly feeds the FY27 order-inflow target.", "ASTERDEF-26Q4-1", "supports",
                          "₹3,150 cr toward the ₹25,000 cr FY27 inflow target."),
    "Halol": ("Halol wire plant starts commercial production, two quarters after the original date.", "high", "Capacity promise delivered late; management had stopped mentioning it.", "NWCABLE-26Q2-3", "updates",
              "Delivered in Q3 FY27, vs Q4 FY26 promised."),
    "pledged": ("Promoter group released pledge on 1.2% of shares.", "medium", "Lower pledge reduces forced-selling risk.", None, None, None),
    "non-convertible": ("Raising ₹1,000 crore via NCDs at 8.9% to fund loan growth.", "medium", "Higher borrowing cost pressures margins.", None, None, None),
    "Credit rating": ("CRISIL reaffirmed AAA/Stable.", "low", "No change in rating.", None, None, None),
}


def _decode_pdf_marker(parts) -> str:
    for p in parts:
        d = p.get("inline_data")
        if d:
            return base64.b64decode(d["data"]).decode(errors="ignore")
    return ""


def generate_json(task, parts, schema=None, system=None, temperature=0.1, max_wait=45.0):
    from finn import gemini
    prompt = " ".join(p.get("text", "") for p in parts)
    marker = _decode_pdf_marker(parts)
    model = gemini.route(task)[0]
    gemini.METER.add(model, {"promptTokenCount": 4000 if marker else 600, "candidatesTokenCount": 300})
    if "keeping a ledger" in prompt:
        m = re.search(r"fake\.local/(\w+)/(Q\d_FY\d\d)\.pdf", marker)
        sym, q = m.group(1), m.group(2).replace("_", " ")
        if sym == "MERIDIAN":  # borrow Lotus's story under Meridian's ids
            return json.loads(json.dumps(TRANSCRIPTS.get(("LOTUSPNT", q), {})).replace("LOTUSPNT", "MERIDIAN")), model
        return json.loads(json.dumps(TRANSCRIPTS.get((sym, q), {"new_promises": [], "updates": []}))), model
    if "quarterly financial results filing" in prompt:
        sym = re.search(r"fake\.local/(\w+)/", marker).group(1)
        return _results(sym), model
    if "change in directors" in prompt:
        return json.loads(json.dumps(PEOPLE)), model
    if "triaging a stock-exchange filing" in prompt:
        for k, (one, imp, why, pid, eff, note) in FILING_SUMMARY.items():
            if k.lower() in prompt.lower():
                links = [{"promise_id": pid, "effect": eff, "note": note}] if pid and pid in prompt else []
                return {"one_line": one, "importance": imp, "why": why, "promise_links": links}, model
        return {"one_line": "Routine update.", "importance": "low", "why": "No bearing on numbers.", "promise_links": []}, model
    if "judging management's promise-keeping" in prompt:
        ledger_blob = json.loads(prompt.split("Ledger:", 1)[1])
        lines = [{"id": p["id"], "line": f"{p['said']} — {p['status'].replace('_', ' ')}."} for p in ledger_blob]
        bad = sum(1 for p in ledger_blob if p["status"] in ("missed", "slipping", "dropped"))
        cred = ("Delivers on headline growth but trims margin guidance quietly and lets capacity dates slide without saying so."
                if bad >= 2 else "Guides conservatively and has met most of what it promised over five calls.")
        return {"credibility": cred, "lines": lines, "overrides": []}, model
    if "Classify each" in prompt:
        ids = re.findall(r"^(\S+)\t", prompt, re.M)
        return {"items": [{"id": i, "category": "unclassified"} for i in ids]}, model
    return {"ok": True}, model


def install(monkeypatch_setattr):
    """Patch FINN's source and model functions with the fakes."""
    from finn import gemini, ledger, readers
    from finn.sources import exchanges, prices, screener
    import pipeline.run as run
    for mod, name, fn in [
        (screener, "fetch_company", fetch_company), (run.screener, "fetch_company", fetch_company),
        (prices, "daily", daily), (run.prices, "daily", daily),
        (exchanges, "announcements", announcements), (run.exchanges, "announcements", announcements),
        (exchanges, "download_attachment", download_attachment), (run.exchanges, "download_attachment", download_attachment),
        (readers, "download_attachment", download_attachment),
        (gemini, "generate_json", generate_json),
    ]:
        monkeypatch_setattr(mod, name, fn)
