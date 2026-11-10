"""Content-addressed JSON cache for AI outputs.

Every document FINN reads with a model is read once, ever: the result is stored
under a key derived from (task, source identity, prompt version). The pipeline
commits this cache to the repo (public/data/cache), and the on-demand API reads
it from the deployed bundle, so evaluators re-opening a company cost nothing.

Read order: writable dir first, then any read-only dirs (the bundled cache).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
BUNDLED = ROOT / "public" / "data" / "cache"


def _writable_dir() -> Path:
    env = os.environ.get("FINN_CACHE_DIR")
    if env:
        return Path(env)
    if os.environ.get("VERCEL"):
        return Path("/tmp/finn-cache")
    return BUNDLED


def key_for(task: str, ident: str, version: str) -> str:
    h = hashlib.sha1(f"{task}|{version}|{ident}".encode()).hexdigest()[:20]
    return f"{task}-{h}"


def _paths(key: str):
    seen = set()
    for d in (_writable_dir(), BUNDLED):
        p = d / f"{key}.json"
        if p not in seen:
            seen.add(p)
            yield p


def get(key: str) -> Optional[Any]:
    for p in _paths(key):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def put(key: str, value: Any) -> None:
    d = _writable_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass  # read-only filesystem: caching is an optimisation, never a failure
