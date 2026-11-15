import datetime as dt
import json

from finn import alerts

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 11, 16, 13, 0, tzinfo=IST)
CONFIG = {"alerts": {"ntfy_topic": "finn-test", "app_url": "https://finn.example"},
          "defaults": {"price_move_pct": 4.0, "volume_multiple": 2.0, "volume_lookback_days": 20}}


def results_item(i="r1", ts="2026-11-16T11:00:00+05:30"):
    return {"id": i, "symbol": "KAYNES", "name": "Kaynes", "ts": ts, "tier": "promise", "category": "results",
            "card": {"type": "results", "ok": True, "quarter": "Q2 FY27",
                     "rows": [{"key": "revenue", "value": 952.5, "yoy": {"pct": 4.4}},
                              {"key": "pat", "value": 45.42, "yoy": {"pct": -61.6}}],
                     "promise_check": [{"verdict": "below", "statement": "Revenue growth of 25% to 30% in FY27"}]}}


def prices(last_chg=-6.0):
    px = [{"d": f"2026-10-{d:02d}", "c": 100.0, "v": 1000} for d in range(1, 28)]
    px.append({"d": "2026-11-13", "c": 100.0 * (1 + last_chg / 100), "v": 3500})
    return px


def test_alert_texts():
    a = alerts.filing_alert(results_item(), "https://finn.example")
    assert a["title"] == "KAYNES: Q2 FY27 results"
    assert a["message"].startswith("Revenue ₹952 cr (+4.4% YoY), PAT ₹45.4 cr (−61.6% YoY).")
    assert "Below a promise" in a["message"] and a["tags"] == ["warning"] and a["priority"] == 4
    assert a["click"] == "https://finn.example/#/c/KAYNES"
    ppl = {"id": "p", "symbol": "TRENT", "ts": "x", "tier": "material", "category": "management",
           "card": {"type": "people", "changes": [{"name": "A B", "action": "appointed", "role": "CFO"}]}}
    assert alerts.filing_alert(ppl, "")["message"] == "A B appointed as CFO."


def test_first_run_marks_existing_as_seen_then_sends_only_new(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "publish", lambda top, a: sent.append((top, a["title"])))
    companies = {"BEL": {"prices": prices()}, "X": {"prices": prices(0.1), "research_only": True}}
    out = alerts.run([results_item()], companies, CONFIG, tmp_path, log=lambda *a: None, now=NOW)
    assert out["started"] and sent == []
    assert set(json.loads((tmp_path / "alerts_sent.json").read_text())["sent"]) >= {"r1", "move-BEL-2026-11-13"}
    new = results_item("r2", "2026-11-16T12:30:00+05:30")
    old = results_item("r3", "2026-11-10T12:30:00+05:30")             # too old to be news
    out = alerts.run([new, old, results_item()], companies, CONFIG, tmp_path, log=lambda *a: None, now=NOW)
    assert out["sent"] == 1 and sent == [("finn-test", "KAYNES: Q2 FY27 results")]
    log = json.loads((tmp_path / "alerts.json").read_text())
    assert log["topic"] == "finn-test" and log["log"][0]["title"] == "KAYNES: Q2 FY27 results"
    assert alerts.run([new], companies, CONFIG, tmp_path, log=lambda *a: None, now=NOW)["sent"] == 0   # never twice


def test_moves_flood_and_failures(tmp_path, monkeypatch):
    (tmp_path / "alerts_sent.json").write_text(json.dumps({"sent": []}))
    calls = []

    def flaky(top, a):
        calls.append(a["title"])
        if a["title"].startswith("BAD"):
            raise RuntimeError("ntfy down")
    monkeypatch.setattr(alerts, "publish", flaky)
    items = [dict(results_item(f"i{n}", f"2026-11-16T{10 + n % 3}:0{n % 10}:00+05:30"), symbol=f"S{n}") for n in range(10)]
    items.append(dict(results_item("bad", "2026-11-16T12:59:00+05:30"), symbol="BAD"))
    companies = {"BEL": {"prices": prices(-6.0)}}
    out = alerts.run(items, companies, CONFIG, tmp_path, log=lambda *a: None, now=NOW)
    assert out["sent"] == alerts.MAX_PER_RUN - 2 and out["errors"] and out["summarised"] == 12 - (alerts.MAX_PER_RUN - 1)
    assert calls[-1].endswith("more things matter")
    sent = set(json.loads((tmp_path / "alerts_sent.json").read_text())["sent"])
    assert "bad" not in sent                                             # a failed alert is retried next run
    move = alerts.move_alert("BEL", {"d": "2026-11-13", "chg": -6.0, "vol_x": 3.5}, [], "")
    assert move["title"] == "BEL down 6.0% on 2026-11-13" and move["message"].endswith("No filing explains it.")


def test_alerts_never_break_a_run(tmp_path, monkeypatch):
    (tmp_path / "alerts_sent.json").write_text("not json")
    assert alerts.run([results_item()], {}, CONFIG, tmp_path, log=lambda *a: None)["sent"] == 0
    assert alerts.run([], {}, {"defaults": {}}, tmp_path, log=lambda *a: None)["note"] == "no topic configured"
