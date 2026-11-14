import json
from pathlib import Path

import pytest

from finn import classify, financials, ledger, periods, triage
from finn.sources import screener

FIX = Path(__file__).parent / "fixtures"


# ---- periods -----------------------------------------------------------------

def test_quarter_labels():
    assert periods.quarter_label("Sep 2025") == "Q2 FY26"
    assert periods.quarter_label("Mar 2026") == "Q4 FY26"
    assert periods.quarter_label("Jun 2026") == "Q1 FY27"
    assert periods.quarter_label("Oct 2025") is None


def test_call_month_to_quarter():
    assert periods.quarter_discussed_on_call("Oct 2025") == "Q2 FY26"
    assert periods.quarter_discussed_on_call("Jan 2026") == "Q3 FY26"
    assert periods.quarter_discussed_on_call("May 2026") == "Q4 FY26"
    assert periods.quarter_discussed_on_call("Jul 2026") == "Q1 FY27"


def test_prev_and_year_ago():
    assert periods.prev_quarter("Q1 FY27") == "Q4 FY26"
    assert periods.year_ago("Q2 FY27") == "Q2 FY26"


# ---- screener parser -----------------------------------------------------------

@pytest.fixture
def company():
    return screener.parse_company_html((FIX / "screener_sample.html").read_text(encoding="utf-8"), "SAMPLE")


def test_screener_identity(company):
    assert company["name"] == "Sample Industries Ltd"
    assert company["bse_code"] == "543210"
    assert company["nse_symbol"] == "SAMPLE"
    assert company["is_lender"] is False


def test_screener_quarters(company):
    q = company["quarters"]
    assert q["periods"][0] == "Q2 FY25" and q["periods"][-1] == "Q2 FY27"
    assert q["rows"]["revenue"][-1] == 1280
    assert q["rows"]["ebitda"][0] == 150
    assert q["rows"]["margin"][0] == 15
    assert q["rows"]["pat"][-1] == 104


def test_screener_concalls_skip_missing_transcripts(company):
    t = company["transcripts"]
    assert [x["quarter"] for x in t] == ["Q2 FY27", "Q1 FY27", "Q4 FY26", "Q2 FY26"]
    assert t[0]["url"].endswith("t-oct26.pdf")


def test_screener_annual_reports(company):
    assert company["annual_reports"][0]["url"].endswith("AR2026.pdf")


# ---- financial arithmetic --------------------------------------------------------

def test_pct_change_edge_cases():
    assert financials.pct_change(110, 100)["pct"] == 10.0
    assert financials.pct_change(5, -10)["label"] == "turned positive"
    assert financials.pct_change(-5, 10)["label"] == "turned negative"
    assert financials.pct_change(-5, -10)["label"].startswith("narrowed")
    assert financials.pct_change(None, 10)["pct"] is None


def test_results_card_units_and_ebitda():
    extracted = {
        "unit": "lakh", "basis": "consolidated", "is_lender": False, "quarter": "Q2 FY27",
        "periods": [
            {"role": "current", "revenue_from_operations": 128000, "other_income": 1000, "total_expenses": 113800,
             "finance_costs": 2400, "depreciation": 3800, "pbt": 13800, "pat": 10400},
            {"role": "previous_quarter", "revenue_from_operations": 123000, "total_expenses": 108800,
             "finance_costs": 2400, "depreciation": 3700, "pbt": 13800, "pat": 10400},
            {"role": "year_ago_quarter", "revenue_from_operations": 115000, "total_expenses": 101500,
             "finance_costs": 2200, "depreciation": 3400, "pbt": 13500, "pat": 10100},
        ]}
    card = financials.results_card(extracted)
    rows = {r["key"]: r for r in card["rows"]}
    assert rows["revenue"]["value"] == 1280.0                 # lakh -> crore
    assert rows["ebitda"]["value"] == pytest.approx(1280 - 1138 + 24 + 38)
    assert rows["revenue"]["yoy"]["pct"] == pytest.approx(11.3, abs=0.1)
    assert card["ebitda_margin"] == pytest.approx(204 / 1280 * 100, abs=0.1)


def test_results_card_lender_uses_ppop():
    card = financials.results_card({"is_lender": True, "unit": "crore", "periods": [
        {"role": "current", "revenue_from_operations": 500, "operating_profit_before_provisions": 200, "pbt": 150, "pat": 112}]})
    rows = {r["key"]: r for r in card["rows"]}
    assert rows["ebitda"]["label"] == "PPOP" and rows["ebitda"]["value"] == 200
    assert card["ebitda_margin"] is None


def test_cross_check(company):
    card = {"quarter": "Q2 FY27", "rows": [{"key": "revenue", "value": 1281}, {"key": "pat", "value": 104}]}
    assert financials.cross_check(card, company["quarters"]) is True
    card["rows"][0]["value"] = 1500
    assert financials.cross_check(card, company["quarters"]) is False


def test_actual_fy_ytd_and_quarter(company):
    q = company["quarters"]
    a = financials.actual_for("revenue_growth", "fy", "Q4 FY27", q, "Q2 FY27", scope="fy")
    # FY27 so far: Q1+Q2 = 2510 vs FY26 Q1+Q2 = 2230
    assert a["ytd"] is True and a["value"] == pytest.approx(12.6, abs=0.1)
    m = financials.actual_for("ebitda_margin", "fy", "Q4 FY26", q, "Q2 FY27", scope="fy")
    assert m["ytd"] is False and m["value"] == pytest.approx(740 / 4730 * 100, abs=0.1)
    assert financials.actual_for("revenue_growth", "constant_currency", "Q4 FY26", q, "Q2 FY27") is None


# ---- classification ---------------------------------------------------------------

@pytest.mark.parametrize("raw,cat,sub", [
    ({"raw_category": "Result", "raw_subcategory": "Financial Results", "headline": "Unaudited Financial Results for the quarter ended September 30, 2026"}, "results", "financials"),
    ({"raw_category": "Board Meeting", "raw_subcategory": "Board Meeting Intimation", "headline": "Board Meeting Intimation for considering financial results"}, "results", "intimation"),
    ({"raw_category": "Company Update", "headline": "Transcript of the earnings conference call"}, "earnings_call", "transcript"),
    ({"raw_category": "Company Update", "headline": "Analyst / Investor Meet - Intimation"}, "investor_meetings", "meeting"),
    ({"raw_category": "Company Update", "headline": "Appointment of Mr. X as Chief Financial Officer"}, "management_change", "top"),
    ({"raw_category": "Company Update", "headline": "Appointment of Ms. Y as Independent Director"}, "management_change", "board"),
    ({"raw_category": "Company Update", "headline": "Credit Rating reaffirmed by CRISIL"}, "credit_rating", "reaffirmed"),
    ({"raw_category": "Company Update", "headline": "CARE Ratings downgrades long-term rating"}, "credit_rating", "downgrade"),
    ({"raw_category": "Company Update", "headline": "Receipt of order worth Rs 500 crore"}, "press_release", "news"),
    ({"raw_category": "Others", "headline": "Certificate under Regulation 74(5) of SEBI (DP) Regulations"}, "unclassified", "compliance"),
    ({"raw_category": "Company Update", "headline": "Allotment of equity shares under ESOP scheme"}, "unclassified", "esop"),
    ({"raw_category": "Company Update", "headline": "Acquisition of 51% stake in ABC Pvt Ltd"}, "M&A", "deal"),
    ({"raw_category": "Company Update", "headline": "Commissioning of new plant at Hosur"}, "capex", "capacity"),
    ({"raw_category": "Company Update", "headline": "Clarification sought on spurt in volume"}, "press_release", "clarification_routine"),
    ({"raw_category": "Company Update", "headline": "Disclosure of pledged shares by promoter"}, "pledging", "pledge"),
])
def test_classify(raw, cat, sub):
    c = classify.classify(raw)
    assert (c["category"], c["subtype"]) == (cat, sub)


def test_classify_unknown_is_low_confidence():
    assert classify.classify({"headline": "Miscellaneous"})["confidence"] == "low"


# ---- ledger ----------------------------------------------------------------------

def _call(new=(), updates=()):
    return {"new_promises": list(new), "updates": list(updates)}


P_GROWTH = {"statement": "FY27 revenue growth of 12–14%", "quote": "we expect 12 to 14% growth", "theme": "growth",
            "metric": "revenue_growth", "basis": "fy", "target_low": 12, "target_high": 14, "unit": "%",
            "horizon": "FY27", "horizon_end": "Q4 FY27", "specificity": "hard"}
P_PLANT = {"statement": "New plant commissioned by Q1 FY27", "quote": "plant will be commissioned by June",
           "theme": "capex", "metric": "capacity", "basis": "other", "horizon": "Q1 FY27", "horizon_end": None,
           "specificity": "hard"}
P_MARGIN = {"statement": "EBITDA margin of 17% in FY26", "quote": "17% margin", "theme": "margin",
            "metric": "ebitda_margin", "basis": "fy", "target_low": 17, "target_high": 17, "unit": "%",
            "horizon": "FY26", "horizon_end": "Q4 FY26", "specificity": "hard"}


def test_ledger_flow_and_statuses(company):
    s = ledger.new_state("SAMPLE", "Sample Industries")
    s = ledger.apply_call(s, "Q2 FY26", "u1", _call(new=[P_MARGIN]))
    s = ledger.apply_call(s, "Q4 FY26", "u2", _call(new=[P_GROWTH, P_PLANT], updates=[
        {"promise_id": "SAMPLE-26Q2-1", "kind": "reiterated", "quote": "on track for 17%"}]))
    ids = {p["statement"]: p["id"] for p in s["promises"]}
    assert ids["New plant commissioned by Q1 FY27"] == "SAMPLE-26Q4-2"
    assert s["promises"][1]["horizon_end"] == "Q4 FY27"
    assert s["promises"][2]["horizon_end"] == "Q1 FY27"           # derived from horizon text
    s = ledger.apply_call(s, "Q1 FY27", "u3", _call(updates=[
        {"promise_id": "SAMPLE-26Q4-1", "kind": "reiterated"}]))
    s = ledger.apply_call(s, "Q2 FY27", "u4", _call(updates=[
        {"promise_id": "SAMPLE-26Q4-1", "kind": "reiterated"}]))
    out = ledger.finalize(s, company["quarters"], "Q2 FY27", use_model=False)
    by = {p["id"]: p for p in out["promises"]}
    # margin: FY26 actual 740/4730 = 15.6% < 17% and due -> missed
    assert by["SAMPLE-26Q2-1"]["status"] == "missed"
    # growth: FY27 YTD 12.6% within 12–14 -> on track
    assert by["SAMPLE-26Q4-1"]["status"] == "on_track"
    # plant: due Q1 FY27, never mentioned again on two calls -> dropped
    assert by["SAMPLE-26Q4-2"]["status"] == "dropped"
    assert out["counts"]["missed"] == 1 and out["counts"]["dropped"] == 1
    assert all(p.get("verdict") for p in out["promises"])


def test_ledger_explicit_kinds_and_raise():
    s = ledger.new_state("X", "X")
    s = ledger.apply_call(s, "Q1 FY27", "u1", _call(new=[P_GROWTH]))
    s = ledger.apply_call(s, "Q2 FY27", "u2", _call(updates=[
        {"promise_id": "X-27Q1-1", "kind": "raised", "new_target_low": 14, "new_target_high": 16}]))
    p = s["promises"][0]
    assert p["target"]["low"] == 14 and p["target"]["unit"] == "%"
    a = ledger.assess(p, {}, "Q2 FY27")
    assert a["status"] == "on_track" and a["revised"] == "better"
    s = ledger.apply_call(s, "Q3 FY27", "u3", _call(updates=[{"promise_id": "X-27Q1-1", "kind": "withdrawn"}]))
    assert ledger.assess(s["promises"][0], {}, "Q3 FY27")["status"] == "dropped"
    assert ledger.open_promises(s) == []


def test_apply_call_is_idempotent_per_quarter():
    s = ledger.new_state("X", "X")
    s = ledger.apply_call(s, "Q1 FY27", "u1", _call(new=[P_GROWTH]))
    s = ledger.apply_call(s, "Q1 FY27", "u1", _call(new=[P_GROWTH]))
    assert len(s["promises"]) == 1


def test_ignores_updates_for_unknown_ids():
    s = ledger.new_state("X", "X")
    s = ledger.apply_call(s, "Q1 FY27", "u1", _call(new=[P_GROWTH]))
    s = ledger.apply_call(s, "Q2 FY27", "u2", _call(updates=[{"promise_id": "nope", "kind": "delivered"}]))
    assert s["promises"][0]["history"][-1]["kind"] == "not_mentioned"


# ---- triage -----------------------------------------------------------------------

def test_tiers_and_reading_rules():
    raw = {"id": "1", "symbol": "S", "headline": "Unaudited Financial Results for quarter ended", "raw_category": "Result",
           "attachment": "https://x/a.pdf"}
    it = triage.base_item(raw, "S")
    assert triage.tier(it) == "promise" and triage.needs_reading(it) == "results"
    it2 = triage.base_item({**raw, "id": "2", "headline": "Board Meeting Intimation to consider financial results"}, "S")
    assert triage.tier(it2) == "routine" and triage.needs_reading(it2) is None
    it3 = triage.base_item({**raw, "id": "3", "headline": "Receipt of order worth Rs 900 crore"}, "S")
    assert triage.tier(it3) == "material" and triage.needs_reading(it3) == "filing"
    it3["importance"] = "low"
    assert triage.tier(it3) == "routine"
    it3["promise_links"] = [{"promise_id": "p"}]
    assert triage.tier(it3) == "promise"
    assert triage.tier(it3, care=set()) == "promise"   # promise links beat settings


def test_promise_check():
    card = {"ok": True, "lender": False, "ebitda_margin": 15.6, "rows": [
        {"key": "revenue", "yoy": {"pct": 11.3}}, {"key": "pat", "yoy": {"pct": 3.0}}]}
    promises = [{"id": "a", "statement": "g", "metric": "revenue_growth", "basis": "fy", "target": {"low": 12, "high": 14}},
                {"id": "b", "statement": "m", "metric": "ebitda_margin", "basis": "fy", "target": {"low": 17, "high": 17}},
                {"id": "c", "statement": "cc", "metric": "revenue_growth", "basis": "constant_currency", "target": {"low": 1, "high": 3}}]
    out = {x["promise_id"]: x for x in triage.promise_check(card, promises)}
    assert out["a"]["verdict"] == "below" and out["b"]["verdict"] == "below" and "c" not in out


def test_contradiction_management_says_delivered_but_table_disagrees(company):
    s = ledger.new_state("SAMPLE", "S")
    s = ledger.apply_call(s, "Q2 FY26", "u1", _call(new=[P_MARGIN]))
    s = ledger.apply_call(s, "Q4 FY26", "u2", _call(updates=[{"promise_id": "SAMPLE-26Q2-1", "kind": "delivered", "reported_value": 17}]))
    out = ledger.finalize(s, company["quarters"], "Q2 FY27", use_model=False)
    p = out["promises"][0]
    assert p["status"] == "missed" and p["contradiction"] is True
    assert "exchange data" in p["reason"]


def test_lower_is_better_guidance_raise_is_slipping():
    cc = {"statement": "Credit cost 1.8-2.0%", "quote": "q", "theme": "balance_sheet", "metric": "cost", "basis": "fy",
          "direction": "lower_is_better", "target_low": 1.8, "target_high": 2.0, "unit": "%", "horizon": "FY27",
          "specificity": "hard"}
    s = ledger.new_state("L", "L")
    s = ledger.apply_call(s, "Q1 FY27", "u1", _call(new=[cc]))
    s = ledger.apply_call(s, "Q2 FY27", "u2", _call(updates=[{"promise_id": "L-27Q1-1", "kind": "raised", "new_target_low": 2.1, "new_target_high": 2.3}]))
    a = ledger.assess(s["promises"][0], {}, "Q2 FY27")
    assert a["status"] == "slipping" and a["revised"] == "worse"


# ---- exchange fallbacks ------------------------------------------------------------

def test_bse_blocked_falls_back_to_nse_and_stops_retrying(monkeypatch):
    import datetime as dt
    from finn import http
    from finn.sources import exchanges
    monkeypatch.setattr(exchanges, "_bse_blocked", False)
    calls = {"bse": 0, "nse": 0}

    def bse(*a, **k):
        calls["bse"] += 1
        raise http.FetchError("bse", 403, "Access Denied")

    def nse(sym, s, e):
        calls["nse"] += 1
        return [{"id": "n1"}]
    monkeypatch.setattr(exchanges, "bse_announcements", bse)
    monkeypatch.setattr(exchanges, "nse_announcements", nse)
    d = dt.date(2026, 11, 10)
    assert exchanges.announcements("INFY", "500209", d, d) == ([{"id": "n1"}], "NSE")
    exchanges.announcements("TCS", "532540", d, d)
    assert calls == {"bse": 1, "nse": 2}          # BSE tried once per run, not per company


def test_bse_tries_browser_session_then_plain(monkeypatch):
    from finn import http
    from finn.sources import exchanges
    tried = []

    class Resp:
        def json(self):
            return {"Table": []}

    def fake_get(url, sess=None, **kw):
        tried.append("browser" if sess == "B" else "plain")
        if sess == "B":
            raise http.FetchError(url, 403, "denied")
        return Resp()
    monkeypatch.setattr(http, "browser_session", lambda: "B")
    monkeypatch.setattr(http, "get", fake_get)
    exchanges._bse_get({})
    assert tried == ["browser", "plain"]


def test_units_are_normalised():
    assert ledger.norm_unit("percent") == "%" and ledger.norm_unit("% YoY") == "%"
    assert ledger.norm_unit("INR crore") == "crore" and ledger.norm_unit("units") == "units"


def test_results_card_completed_or_rebuilt_from_table(company):
    q = company["quarters"]
    card = {"ok": True, "quarter": "Q2 FY27", "cross_check": True, "ebitda_margin": None, "rows": [
        {"key": "revenue", "label": "Revenue", "value": 1280, "qoq": {}, "yoy": {}},
        {"key": "ebitda", "label": "EBITDA", "value": 190, "qoq": {}, "yoy": {}},
        {"key": "pbt", "label": "PBT", "value": None, "qoq": {}, "yoy": {}},
        {"key": "pat", "label": "PAT", "value": None, "qoq": {}, "yoy": {}}]}
    out = financials.complete_from_table(card, q)
    rows = {r["key"]: r for r in out["rows"]}
    assert rows["pat"]["value"] == 104 and rows["pat"]["src"] == "table"
    assert out["filled_from_table"] == ["PBT", "PAT"] and out["ebitda_margin"] == pytest.approx(14.8, abs=0.1)
    bad = {"ok": True, "quarter": "Q2 FY27", "cross_check": False, "rows": [{"key": "revenue", "label": "Revenue", "value": 17}]}
    rebuilt = financials.complete_from_table(bad, q)
    assert rebuilt["source"] == "table" and rebuilt["rows"][0]["value"] == 1280
    assert rebuilt["rows"][0]["yoy"]["pct"] == pytest.approx((1280 / 1150 - 1) * 100, abs=0.1)


# ---- annual fundamentals -------------------------------------------------------------

def test_screener_annual_tables_and_top_ratios(company):
    pl, bs = company["annual"]["pl"], company["annual"]["bs"]
    assert pl["periods"][0] == "FY20" and pl["periods"][-1] == "TTM"
    assert pl["rows"]["revenue"][-2] == 4730 and pl["rows"]["pat"][-1] == 430
    assert bs["periods"][-1] == "Sep 2026" and bs["rows"]["borrowings"][-1] == 750
    assert company["annual"]["cf"]["rows"]["cfo"][2] == -20
    assert company["annual"]["ratios"]["rows"]["wc_days"][-1] == 80
    t = company["top_ratios"]
    assert t["market_cap_cr"] == 12345 and t["pe"] == 28.4 and t["roe"] == 17.2 and t["high"] == 1500


def test_fundamentals_summary(company):
    from finn import fundamentals
    f = fundamentals.summarize(company)
    tr = f["trajectory"]
    assert tr["years"][-1] == "FY26" and tr["rev_cagr_5y"] == pytest.approx(((4730 / 2300) ** 0.2 - 1) * 100, abs=0.1)
    assert any("compounded" in n for n in tr["notes"])
    b = f["balance"]
    assert b["period"] == "Sep 2026" and b["debt_to_equity"] == round(750 / 2200, 2)
    assert any("Working-capital days stretched" in n for n in b["notes"])
    c = f["cash"]
    assert c["conversion"] == round((170 + 200 - 20 + 300 + 380) / (190 + 230 + 280 + 330 + 416) * 100)
    assert any("negative in FY24" in n for n in c["notes"])
    assert f["snapshot"]["period"] == "TTM" and f["snapshot"]["pe"] == 28.4
    assert "compounded" in fundamentals.facts_for_prompt(f)


def test_fundamentals_lender_and_missing():
    from finn import fundamentals
    assert fundamentals.summarize({"annual": {}}) is None
    co = {"is_lender": True, "annual": {"pl": {"periods": ["FY25", "FY26"], "rows": {"revenue": [100, 120], "pat": [20, 25]}},
                                         "bs": {"periods": ["FY26"], "rows": {"borrowings": [900], "reserves": [100], "equity_capital": [10]}}}}
    f = fundamentals.summarize(co)
    assert f["balance"]["debt_to_equity"] is None and "raw material" in f["balance"]["notes"][0]


def test_results_second_pass_fills_only_missing_lines(monkeypatch):
    from finn import gemini, readers
    first = {"is_results_document": True, "basis": "consolidated", "unit": "crore", "periods": [
        {"role": "current", "revenue_from_operations": 1000, "total_expenses": 800, "finance_costs": None,
         "depreciation": None, "pbt": 210, "pat": 160},
        {"role": "previous", "revenue_from_operations": 950, "finance_costs": None, "depreciation": None}]}
    assert readers._missing(first) == ["finance_costs", "depreciation"]
    seen = {}

    def fake(task, parts, schema=None, **kw):
        seen["prompt"] = parts[0]["text"]
        return {"periods": [{"role": "current", "finance_costs": 12, "depreciation": 30, "pat": 999},
                            {"role": "previous", "finance_costs": 11, "depreciation": 29}]}, "m"
    monkeypatch.setattr(gemini, "generate_json", fake)
    monkeypatch.setattr(readers, "_results_text", lambda b: "Finance costs 12 11 Depreciation 30 29")
    out = readers._fill_missing(first, b"%PDF")
    cur = out["periods"][0]
    assert (cur["finance_costs"], cur["depreciation"], cur["pat"]) == (12, 30, 160)   # read lines untouched
    assert "finance_costs, depreciation" in seen["prompt"]
    lender = {"is_lender": True, "periods": [{"role": "current", "revenue_from_operations": 5, "pbt": 2, "pat": 1}]}
    assert readers._missing(lender) == []          # lenders have no EBITDA lines to chase


def test_web_bio_rejects_unsure_or_unsourced_answers(monkeypatch, tmp_path):
    from finn import gemini, readers
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path))
    answers = iter([("UNKNOWN", "m", [{"title": "x", "url": "https://x"}]),
                    ("Twenty years at a bank [1].", "m", []),
                    ("Spent 20 years at a large private bank, latterly as its treasurer; chartered accountant [1, 2].", "m",
                     [{"title": "a.in", "url": "https://a.in/p"}])])
    monkeypatch.setattr(gemini, "search_text", lambda task, prompt, **kw: next(answers))
    assert readers.web_bio("A One", "CFO", "Co") is None
    assert readers.web_bio("B Two", "CFO", "Co") is None           # no sources: not shown
    got = readers.web_bio("C Three", "CFO", "Co")
    assert got["text"].endswith("chartered accountant.") and "[" not in got["text"]
    assert readers.web_bio("C Three", "CFO", "Co") == got           # cached

    def boom(*a, **k):
        raise gemini.GeminiError("grounding not available on this tier")
    monkeypatch.setattr(gemini, "search_text", boom)
    assert readers.web_bio("D Four", "CFO", "Co") is None
