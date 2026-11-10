"""Generate FICTIONAL sample data by running the real pipeline against fakes.

    python dev/make_fixtures.py          -> dev/fixtures/  (served at /dev-fixtures/ by dev/server.py)

Used for UI development and the end-to-end test. Never deployed.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dev" / "fixtures"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    os.environ["FINN_DATA_DIR"] = str(OUT)
    os.environ["FINN_CONFIG"] = str(ROOT / "dev" / "fixture_config.json")
    os.environ["FINN_CACHE_DIR"] = tempfile.mkdtemp(prefix="finn-cache-")
    os.environ["GEMINI_API_KEY"] = "fake"
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "dev"))
    import fakes
    import pipeline.run as run
    fakes.install(lambda mod, name, fn: setattr(mod, name, fn))
    run.main(["--mode", "full"])


if __name__ == "__main__":
    main()
