import json

import pytest

from finn import gemini


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def ok(payload, tokens=(100, 20)):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}, "finishReason": "STOP"}],
                      "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]}})


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(gemini, "_throttle", lambda m: None)
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    gemini._exhausted.clear()
    gemini.METER.__init__()


def test_routes_to_first_model(monkeypatch):
    calls = []
    monkeypatch.setattr(gemini.requests, "post", lambda url, **kw: calls.append(url) or ok({"a": 1}))
    data, model = gemini.generate_json("verdict", [{"text": "x"}])
    assert data == {"a": 1} and model == gemini.ROUTES["verdict"][0]
    assert gemini.METER.calls[model] == 1 and gemini.METER.tokens_in == 100


def test_daily_quota_falls_back_and_remembers(monkeypatch):
    first, second = gemini.ROUTES["verdict"][:2]
    daily = Resp(429, {"error": {"code": 429, "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
    seen = []

    def post(url, **kw):
        seen.append(url)
        return daily if first in url else ok({"b": 2})
    monkeypatch.setattr(gemini.requests, "post", post)
    data, model = gemini.generate_json("verdict", [{"text": "x"}])
    assert model == second and first in gemini._exhausted
    seen.clear()
    gemini.generate_json("verdict", [{"text": "x"}])
    assert all(first not in u for u in seen)          # exhausted model skipped next time


def test_per_minute_limit_waits_then_succeeds(monkeypatch):
    rpm = Resp(429, {"error": {"details": [{"retryDelay": "7s"}]}})
    seq = [rpm, ok({"c": 3})]
    monkeypatch.setattr(gemini.requests, "post", lambda url, **kw: seq.pop(0))
    data, model = gemini.generate_json("read_pdf", [{"text": "x"}])
    assert data == {"c": 3} and model == gemini.ROUTES["read_pdf"][0]


def test_missing_model_and_schema_dialect(monkeypatch):
    first = gemini.ROUTES["promises"][0]
    bodies = []

    def post(url, json=None, **kw):
        bodies.append(json)
        if first in url:
            return Resp(404, {"error": {"message": "not found"}})
        if "responseSchema" in json["generationConfig"]:
            return Resp(400, {"error": {"message": "Invalid JSON payload: unknown field in schema"}})
        return ok({"d": 4})
    monkeypatch.setattr(gemini.requests, "post", post)
    data, model = gemini.generate_json("promises", [{"text": "x"}], schema={"type": "OBJECT"})
    assert data == {"d": 4} and "responseSchema" not in bodies[-1]["generationConfig"]


def test_env_override(monkeypatch):
    monkeypatch.setenv("FINN_MODEL_CLASSIFY", "gemma-x, gemini-y")
    assert gemini.route("classify") == ["gemma-x", "gemini-y"]


def test_parse_fenced_json():
    assert gemini._parse_json("```json\n{\"x\": 1}\n```") == {"x": 1}
    assert gemini._parse_json("noise {\"y\": [1]} trailing") == {"y": [1]}


def test_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(gemini.NoKey):
        gemini.generate_json("classify", [{"text": "x"}])


def test_high_demand_503_is_retried_on_same_model(monkeypatch):
    seq = [Resp(503, {"error": {"message": "high demand"}}), ok({"e": 5})]
    monkeypatch.setattr(gemini.requests, "post", lambda url, **kw: seq.pop(0))
    data, model = gemini.generate_json("read_pdf", [{"text": "x"}])
    assert data == {"e": 5} and model == gemini.ROUTES["read_pdf"][0]


def test_quick_mode_skips_waits_and_moves_on(monkeypatch):
    """With a person waiting (the web app), a rate-limited model is skipped at once."""
    from finn import gemini
    calls, slept = [], []
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(gemini.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(gemini, "_throttle", lambda m: None)
    monkeypatch.setattr(gemini, "_exhausted", set())

    class R:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, ""

        def json(self):
            return self._b

    def post(url, **kw):
        model = url.split("/models/")[1].split(":")[0]
        calls.append(model)
        if model == gemini.route("verdict")[0]:
            return R(429, {"error": {"message": "slow down", "details": [{"retryDelay": "20s"}]}})
        return R(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}], "usageMetadata": {}})
    monkeypatch.setattr(gemini.requests, "post", post)
    token = gemini.QUICK.set(True)
    try:
        data, model = gemini.generate_json("verdict", [{"text": "x"}])
    finally:
        gemini.QUICK.reset(token)
    assert data == {"ok": True} and model != gemini.route("verdict")[0]
    assert calls[0] == gemini.route("verdict")[0] and calls.count(calls[0]) == 1 and not slept
