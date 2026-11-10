"""Freeze the current data as the demo snapshot, or unfreeze it.

    python -m pipeline.freeze            # app treats the data's timestamp as "now"
    python -m pipeline.freeze --off      # back to live behaviour

A live pipeline run also turns snapshot mode off.
"""
import json
import sys
from pathlib import Path

META = Path(__file__).resolve().parent.parent / "public" / "data" / "meta.json"


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    meta["snapshot"] = "--off" not in sys.argv
    META.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(("Snapshot ON at " + meta.get("generated_at", "?")) if meta["snapshot"] else "Snapshot OFF")


if __name__ == "__main__":
    main()
