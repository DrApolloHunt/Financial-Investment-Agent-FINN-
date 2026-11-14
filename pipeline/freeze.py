"""Freeze the current data as the demo snapshot, or unfreeze it.

    python -m pipeline.freeze            # app treats the data's timestamp as "now"
    python -m pipeline.freeze --latest   # ...or the moment just after the newest filing, when
                                         # nothing was filed between it and the data run
    python -m pipeline.freeze --off      # back to live behaviour

A live pipeline run also turns snapshot mode off.
"""
import datetime as dt
import json
import sys
from pathlib import Path

META = Path(__file__).resolve().parent.parent / "public" / "data" / "meta.json"
FEED = META.parent / "feed.json"


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    meta["snapshot"] = "--off" not in sys.argv
    meta.pop("as_of", None)
    if meta["snapshot"] and "--latest" in sys.argv:
        stamps = [it["ts"] for it in json.loads(FEED.read_text(encoding="utf-8"))["items"] if it.get("ts")]
        newest = max(dt.datetime.fromisoformat(t) for t in stamps)
        meta["as_of"] = (newest + dt.timedelta(minutes=1)).replace(second=0).isoformat()
    META.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(("Snapshot ON at " + meta.get("as_of", meta.get("generated_at", "?"))) if meta["snapshot"] else "Snapshot OFF")


if __name__ == "__main__":
    main()
