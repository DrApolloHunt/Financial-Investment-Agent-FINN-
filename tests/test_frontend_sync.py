import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_categories_js_matches_config():
    cfg = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))
    js = (ROOT / "public" / "js" / "categories.js").read_text(encoding="utf-8")
    arr = json.loads(re.search(r"CATEGORIES = (\[.*?\]);", js, re.S).group(1))
    assert arr == cfg["categories"]


def test_routine_subtypes_match():
    cfg = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))["routine_subtypes"]
    js = (ROOT / "public" / "js" / "logic.js").read_text(encoding="utf-8")
    for cat, subs in cfg.items():
        line = re.search(rf"{re.escape(cat)}: \[(.*?)\]", js).group(1)
        assert sorted(re.findall(r'"(\w+)"', line)) == sorted(subs), cat
