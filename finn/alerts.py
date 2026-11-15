"""Phone alerts through ntfy (https://ntfy.sh): free, open source, no sign-up.

After each data refresh, FINN sends one notification per new item that earns attention:
a filing that bears on a promise (results always do), a material filing, or a price or
volume move beyond the default thresholds on the latest trading day. Tapping an alert
opens that company in FINN. Each alert is sent once; the first run only marks what
already exists as seen, so subscribers are not flooded with the backlog.

Anyone can subscribe to the topic with the free ntfy app. Topic names on ntfy.sh are
public, so the name is hard to guess but not secret.

    python -m finn.alerts --test     # send a test alert (and start the log if needed)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests

from . import moves

ROOT = Path(__file__).resolve().parent.parent
SERVER = os.environ.get("FINN_NTFY_SERVER", "https://ntfy.sh")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_PER_RUN = 8          # a summary alert stands in for the rest
FRESH_HOURS = 36         # an older filing is news no more
KEEP_SENT = 3000

_LABELS: Optional[dict] = None


def label(category: str) -> str:
    global _LABELS
    if _LABELS is None:
        try:
            cats = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))["categories"]
            _LABELS = {c["id"]: c["label"] for c in cats}
        except Exception:
            _LABELS = {}
    return _LABELS.get(category, category.replace("_", " ").capitalize())


def topic(config: dict) -> str:
    return os.environ.get("FINN_NTFY_TOPIC") or (config.get("alerts") or {}).get("ntfy_topic") or ""


def app_url(config: dict) -> str:
    return (config.get("alerts") or {}).get("app_url", "").rstrip("/")


def _pct(v: Optional[float]) -> str:
    return "" if v is None else f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.1f}%"


def _cr(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"₹{v:,.0f} cr" if abs(v) >= 100 else f"₹{v:.1f} cr"


def _short(s: str, n: int = 220) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip(" ,;") + "…"


def filing_alert(it: dict, base: str) -> dict:
    sym = it["symbol"]
    card = it.get("card") or {}
    click = f"{base}/#/c/{sym}" if base else ""
    if card.get("type") == "results" and card.get("ok"):
        rows = {r["key"]: r for r in card.get("rows", [])}
        parts = []
        for key, name in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pat", "PAT")):
            r = rows.get(key)
            if r:
                yoy = (r.get("yoy") or {}).get("pct")
                parts.append(f"{name} {_cr(r['value'])}" + (f" ({_pct(yoy)} YoY)" if yoy is not None else ""))
        below = [p for p in card.get("promise_check") or [] if p.get("verdict") == "below"]
        msg = ", ".join(parts) + "."
        if below:
            msg += f" Below a promise: {_short(below[0]['statement'], 120)}"
        return {"title": f"{sym}: {card.get('quarter') or 'quarterly'} results", "message": msg,
                "tags": ["warning"] if below else ["bar_chart"], "priority": 4, "click": click}
    if card.get("type") == "people":
        verbs = {"appointed": "appointed", "resigned": "resigned", "retired": "retiring",
                 "redesignated": "takes a new role", "ceased": "left"}
        lines = [f"{c.get('name')} {verbs.get(c.get('action'), 'changes role')}"
                 + (f" as {c['role']}" if c.get("role") else "") for c in card.get("changes", [])[:3]]
        return {"title": f"{sym}: management change", "message": _short(". ".join(lines) + "."),
                "tags": ["bust_in_silhouette"], "priority": 4 if it.get("tier") == "promise" else 3, "click": click}
    undermines = any(l.get("effect") == "undermines" for l in it.get("promise_links") or [])
    msg = _short(it.get("summary") or it.get("headline") or "")
    if undermines:
        msg += " It cuts against a promise."
    return {"title": f"{sym}: {label(it.get('category', ''))}", "message": msg,
            "tags": ["warning"] if undermines else ["page_facing_up"],
            "priority": 4 if it.get("tier") == "promise" else 3, "click": click}


def move_alert(sym: str, m: dict, why: list[dict], base: str) -> dict:
    up = m["chg"] >= 0
    msg = f"On {m['vol_x']:.1f}× its usual volume. " if m.get("vol_x") else ""
    if why:
        msg += f"After a filing: {_short(why[0].get('summary') or why[0].get('headline'), 160)}"
    else:
        msg += "No filing explains it."
    return {"title": f"{sym} {'up' if up else 'down'} {abs(m['chg']):.1f}% on {m['d']}", "message": msg,
            "tags": ["chart_with_upwards_trend" if up else "chart_with_downwards_trend"],
            "priority": 3 if why else 4, "click": f"{base}/#/c/{sym}" if base else ""}


def compose(items: list[dict], companies: dict, config: dict, sent: set,
            now: Optional[dt.datetime] = None) -> list[tuple[str, dict]]:
    """(key, alert) pairs for everything new that earns attention, newest first."""
    now = now or dt.datetime.now(IST)
    base = app_url(config)
    d = config.get("defaults", {})
    out = []
    for it in sorted(items, key=lambda x: x.get("ts") or "", reverse=True):
        if it["id"] in sent or it.get("tier") not in ("promise", "material") or not it.get("ts"):
            continue
        if now - dt.datetime.fromisoformat(it["ts"]) > dt.timedelta(hours=FRESH_HOURS):
            continue
        out.append((it["id"], filing_alert(it, base)))
    for sym, co in companies.items():
        if co.get("research_only"):
            continue
        for m in moves.unusual(co.get("prices") or [], d.get("price_move_pct", 4.0), d.get("volume_multiple", 2.0),
                               d.get("volume_lookback_days", 20), last_n=1):
            key = f"move-{sym}-{m['d']}"
            if key in sent or (now.date() - dt.date.fromisoformat(m["d"])).days > 3:
                continue
            why = moves.pair(m, [it for it in items if it["symbol"] == sym])
            out.append((key, move_alert(sym, m, why, base)))
    return out


def all_keys(items: list[dict], companies: dict, config: dict) -> set:
    """Everything that exists now, for the first run to mark as seen."""
    d = config.get("defaults", {})
    keys = {it["id"] for it in items}
    for sym, co in companies.items():
        for m in moves.unusual(co.get("prices") or [], d.get("price_move_pct", 4.0), d.get("volume_multiple", 2.0),
                               d.get("volume_lookback_days", 20), last_n=5):
            keys.add(f"move-{sym}-{m['d']}")
    return keys


def publish(top: str, alert: dict) -> dict:
    body = {"topic": top, **{k: v for k, v in alert.items() if v}}
    r = requests.post(SERVER, json=body, timeout=15)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:300]}


def _paths(data_dir: Path) -> tuple[Path, Path]:
    return data_dir / "alerts.json", data_dir / "alerts_sent.json"


def run(items: list[dict], companies: dict, config: dict, data_dir: Path, log=print,
        now: Optional[dt.datetime] = None) -> dict:
    """Send what is new and record it. Never raises: alerts must not break a data refresh."""
    top = topic(config)
    pub_path, sent_path = _paths(data_dir)
    if not top:
        return {"sent": 0, "note": "no topic configured"}
    try:
        state = json.loads(sent_path.read_text(encoding="utf-8")) if sent_path.exists() else None
        public = json.loads(pub_path.read_text(encoding="utf-8")) if pub_path.exists() else {"log": []}
        public["topic"] = top
        if state is None:
            seen = all_keys(items, companies, config)
            sent_path.write_text(json.dumps({"sent": sorted(seen)}), encoding="utf-8")
            pub_path.write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
            log(f"alerts: started; {len(seen)} existing items marked as seen")
            return {"sent": 0, "started": True}
        sent = set(state.get("sent", []))
        todo = compose(items, companies, config, sent, now)
        batch = todo[:MAX_PER_RUN] if len(todo) <= MAX_PER_RUN else todo[: MAX_PER_RUN - 1]
        n_ok, errors = 0, []
        stamp = (now or dt.datetime.now(IST)).isoformat(timespec="seconds")
        for key, alert in batch:
            try:
                publish(top, alert)
                n_ok += 1
                public["log"].insert(0, {"at": stamp, **alert})
            except Exception as e:  # noqa: BLE001 - one failed alert must not stop the rest
                errors.append(f"{key}: {e}")
                continue
            sent.add(key)
        rest = todo[len(batch):]
        if rest:
            try:
                base = app_url(config)
                publish(top, {"title": f"{len(rest)} more things matter", "message": "Open FINN to see them all.",
                              "tags": ["bell"], "priority": 3, "click": f"{base}/#/" if base else ""})
                sent.update(k for k, _ in rest)
            except Exception as e:  # noqa: BLE001
                errors.append(f"summary: {e}")
        public["log"] = public["log"][:20]
        sent_path.write_text(json.dumps({"sent": sorted(sent)[-KEEP_SENT:]}), encoding="utf-8")
        pub_path.write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
        log(f"alerts: {n_ok} sent{f', {len(rest)} summarised' if rest else ''}{f', errors {errors}' if errors else ''}")
        return {"sent": n_ok, "summarised": len(rest), "errors": errors}
    except Exception as e:  # noqa: BLE001
        log(f"alerts: skipped ({e})")
        return {"sent": 0, "error": str(e)}


def _latest(items: list[dict]) -> dt.datetime:
    stamps = [dt.datetime.fromisoformat(it["ts"]) for it in items if it.get("ts")]
    return max(stamps) + dt.timedelta(minutes=1) if stamps else dt.datetime.now(IST)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    data_dir = Path(os.environ.get("FINN_DATA_DIR") or ROOT / "public" / "data")
    config = json.loads((ROOT / "config" / "portfolio.json").read_text(encoding="utf-8"))
    top = topic(config)
    if not top:
        print("no ntfy topic configured")
        return 1
    if "--test" in argv:
        feed = json.loads((data_dir / "feed.json").read_text(encoding="utf-8"))
        companies = {}
        for c in config["portfolio"]:
            p = data_dir / "companies" / f"{c['symbol']}.json"
            if p.exists():
                companies[c["symbol"]] = json.loads(p.read_text(encoding="utf-8"))
        run(feed["items"], companies, config, data_dir)          # starts the log on first use
        base = app_url(config)
        d = config.get("defaults", {})
        alert = {"title": "FINN alerts are on",
                 "message": ("You will hear from FINN when results land, a filing bears on a promise, a material "
                             f"filing arrives, or a price moves beyond ±{d.get('price_move_pct', 4):g}% or "
                             f"{d.get('volume_multiple', 2):g}× its usual volume. Tap to open FINN."),
                 "tags": ["bell"], "priority": 3, "click": f"{base}/#/" if base else ""}
        reply = publish(top, alert)
        print("ntfy reply:", json.dumps(reply)[:300])
        sent_now = [alert]
        # and the newest real alert, so the format can be seen today (marked as an example)
        cands = (compose(feed["items"], companies, config, set(), now=dt.datetime.now(IST))
                 or compose(feed["items"], companies, config, set(), now=_latest(feed["items"])))
        example = next((c for c in cands if "results" in c[1]["title"]), cands[0] if cands else None)
        if example:
            ex = {**example[1], "title": f"Example: {example[1]['title']}"}
            print("ntfy reply:", json.dumps(publish(top, ex))[:300])
            sent_now.insert(0, ex)
        pub_path, _ = _paths(data_dir)
        public = json.loads(pub_path.read_text(encoding="utf-8"))
        stamp = dt.datetime.now(IST).isoformat(timespec="seconds")
        public["log"] = ([{"at": stamp, **a} for a in sent_now] + public.get("log", []))[:20]
        pub_path.write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
        got = requests.get(f"{SERVER}/{top}/json", params={"poll": "1", "since": "1h"}, timeout=15)
        print("poll:", got.status_code, got.text[:600].replace("\n", " | "))
        n = sum(1 for line in got.text.splitlines() if '"message"' in line and '"event"' in line)
        print(f"test alert sent to {SERVER}/{top}; the topic now holds {n} message(s) from the last hour")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
