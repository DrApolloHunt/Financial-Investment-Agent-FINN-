"""Gemini REST client with task-based model routing.

Routing principle: the cheapest model that can do the job.
  - Rules first (no model at all) for classifying filings.
  - Flash-Lite (free tier ~500 requests/day) for bulk reading: transcripts,
    results PDFs, filings.
  - Flash (free tier ~20 requests/day) only for the one reasoning step per
    company: reconciling promises across quarters into verdicts.
Each route is a fallback chain: if a model is missing or its daily quota is
spent, the next one is used. Every call is metered so the app can show cost.
Override any route with env FINN_MODEL_<TASK>=model-a,model-b.
"""
from __future__ import annotations

import base64
import contextvars
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

API = "https://generativelanguage.googleapis.com/v1beta"

ROUTES: dict[str, list[str]] = {
    "classify": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "read_pdf": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "promises": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "verdict": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "web_bio": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
}

# Free-tier requests per minute (conservative). Unknown models default to 5.
RPM = {"flash-lite": 14, "flash": 5}

MAX_INLINE_BYTES = 15 * 1024 * 1024


class GeminiError(RuntimeError):
    pass


class NoKey(GeminiError):
    pass


@dataclass
class Meter:
    calls: dict = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    fallbacks: list = field(default_factory=list)

    def add(self, model: str, usage: dict):
        self.calls[model] = self.calls.get(model, 0) + 1
        self.tokens_in += int(usage.get("promptTokenCount", 0) or 0)
        self.tokens_out += int(usage.get("candidatesTokenCount", 0) or 0)

    def as_dict(self):
        return {"calls": self.calls, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "fallbacks": self.fallbacks[-20:]}


METER = Meter()
_exhausted: set[str] = set()
_last_call: dict[str, float] = {}
_lock = threading.Lock()


def api_key() -> str:
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not k:
        raise NoKey("GEMINI_API_KEY is not set")
    return k


def route(task: str) -> list[str]:
    env = os.environ.get(f"FINN_MODEL_{task.upper()}")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    return ROUTES[task]


def _rpm(model: str) -> int:
    if "lite" in model:
        return RPM["flash-lite"]
    if "flash" in model:
        return RPM["flash"]
    return 5


def _throttle(model: str):
    gap = 60.0 / _rpm(model)
    with _lock:
        now = time.time()
        wait = _last_call.get(model, 0) + gap - now
        _last_call[model] = max(now, _last_call.get(model, 0) + gap)
    if wait > 0:
        time.sleep(wait)


def pdf_part(pdf_bytes: bytes) -> dict:
    """Inline a PDF, or fall back to extracted text if it is too large."""
    if len(pdf_bytes) <= MAX_INLINE_BYTES:
        return {"inline_data": {"mime_type": "application/pdf",
                                "data": base64.b64encode(pdf_bytes).decode()}}
    return {"text": "DOCUMENT TEXT (extracted):\n" + pdf_text(pdf_bytes, max_chars=400_000)}


def pdf_text(pdf_bytes: bytes, max_chars: int = 200_000) -> str:
    import io
    from pypdf import PdfReader
    out, n = [], 0
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        t = page.extract_text() or ""
        out.append(t)
        n += len(t)
        if n > max_chars:
            break
    return "\n".join(out)[:max_chars]


def _parse_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise


def _retry_delay(err: dict) -> float:
    for d in err.get("details", []) or []:
        rd = d.get("retryDelay")
        if rd:
            try:
                return float(str(rd).rstrip("s"))
            except ValueError:
                pass
    return 20.0


# When a person is waiting on the screen, don't sit out rate limits or retries on one model:
# move to the next in the route at once. The data job keeps the patient behaviour.
QUICK: contextvars.ContextVar[bool] = contextvars.ContextVar("finn_quick", default=False)


def _is_daily(err: dict) -> bool:
    blob = json.dumps(err)
    return "PerDay" in blob or "per day" in blob.lower()


def _call(task: str, parts: list[dict], schema: Optional[dict], json_mode: bool,
          system: Optional[str], temperature: float, max_wait: float,
          tools: Optional[list] = None, accept=None) -> tuple[Any, str, dict]:
    """Shared request loop: route fallback, throttling, 429/5xx handling.
    `accept(text, candidate)` turns a reply into a result or raises ValueError to retry."""
    key = api_key()
    errors = []
    for model in route(task):
        if model in _exhausted:
            continue
        use_schema = schema is not None
        for attempt in range(3):
            cfg: dict = {"temperature": temperature}
            if json_mode:
                cfg["responseMimeType"] = "application/json"
                if use_schema:
                    cfg["responseSchema"] = schema
            body: dict = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
            if tools:
                body["tools"] = tools
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            _throttle(model)
            try:
                r = requests.post(f"{API}/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key}, json=body, timeout=120)
            except requests.RequestException as e:
                errors.append(f"{model}: network {e}")
                time.sleep(2)
                continue
            if r.status_code == 200:
                data = r.json()
                METER.add(model, data.get("usageMetadata", {}))
                cands = data.get("candidates") or []
                if not cands:
                    errors.append(f"{model}: no candidates ({data.get('promptFeedback')})")
                    break
                c = cands[0]
                text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []))
                if not text and c.get("finishReason") == "RECITATION":
                    parts = parts + [{"text": "Do not quote long passages verbatim; paraphrase and keep any quote under 20 words."}]
                    continue
                try:
                    return accept(text, c), model, c
                except (json.JSONDecodeError, ValueError):
                    errors.append(f"{model}: unparseable output")
                    continue
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {"message": r.text[:200]}
            if r.status_code == 429:
                if _is_daily(err):
                    _exhausted.add(model)
                    METER.fallbacks.append(f"{model} daily quota spent -> next model")
                    break
                delay = _retry_delay(err)
                if QUICK.get() or delay > max_wait:
                    METER.fallbacks.append(f"{model} rate-limited {delay:.0f}s -> next model")
                    break
                time.sleep(delay + 1)
                continue
            if r.status_code == 404:
                METER.fallbacks.append(f"{model} not available -> next model")
                break
            if r.status_code in (500, 503) and attempt < 2 and not QUICK.get():
                time.sleep(8 * (attempt + 1))  # "high demand" spikes are short
                continue
            if r.status_code == 400 and use_schema and "schema" in json.dumps(err).lower():
                use_schema = False  # tolerate schema dialect differences
                continue
            errors.append(f"{model}: {r.status_code} {err.get('message', '')[:160]}")
            break
        else:
            errors.append(f"{model}: gave up after 3 attempts")   # e.g. repeated short rate limits
    raise GeminiError("; ".join(errors) or f"all models for '{task}' unavailable")


def generate_json(task: str, parts: list[dict], schema: Optional[dict] = None,
                  system: Optional[str] = None, temperature: float = 0.1,
                  max_wait: float = 45.0) -> tuple[Any, str]:
    """Run a task through its route. Returns (parsed_json, model_used)."""
    data, model, _ = _call(task, parts, schema, True, system, temperature, max_wait,
                           accept=lambda text, c: _parse_json(text))
    return data, model


def search_text(task: str, prompt: str, temperature: float = 0.1,
                max_wait: float = 20.0) -> tuple[str, str, list[dict]]:
    """A plain-text answer grounded in Google Search. Returns (text, model, sources).
    Search grounding may not be offered on every free-tier model; callers treat
    any GeminiError as "no answer"."""
    def accept(text, c):
        if not text.strip():
            raise ValueError("empty")
        return text.strip()
    text, model, cand = _call(task, [{"text": prompt}], None, False, None, temperature, max_wait,
                              tools=[{"google_search": {}}], accept=accept)
    meta = cand.get("groundingMetadata") or {}
    sources, seen = [], set()
    for ch in meta.get("groundingChunks") or []:
        web = ch.get("web") or {}
        uri, title = web.get("uri"), web.get("title") or ""
        if uri and uri.startswith("http") and title not in seen:
            seen.add(title)
            sources.append({"title": title or uri, "url": uri})
    return text, model, sources[:3]


def list_models() -> list[str]:
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": api_key()},
                     params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    return [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])]
