"""Local dev server: static app + the same /api functions Vercel runs.

    python dev/server.py [port]
Open http://localhost:8000            (real data in public/data)
     http://localhost:8000/?fixtures  (fictional sample data from dev/fixtures)
"""
import importlib.util
import mimetypes
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PUBLIC, FIXTURES = ROOT / "public", ROOT / "dev" / "fixtures"
FAKE = "--fake" in sys.argv
_api = {}


def api_class(name):
    if name not in _api:
        f = ROOT / "api" / f"{name}.py"
        if not f.exists():
            return None
        spec = importlib.util.spec_from_file_location(f"api_{name}", f)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        if FAKE:
            sys.path.insert(0, str(ROOT / "dev"))
            import fakes
            if hasattr(mod, "download_attachment"):
                mod.download_attachment = fakes.download_attachment
        _api[name] = mod.handler
    return _api[name]


class Dev(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PUBLIC), **kw)

    def _api(self):
        name = self.path.split("?", 1)[0].removeprefix("/api/").strip("/")
        cls = api_class(name)
        if not cls:
            self.send_error(404)
            return True
        self.__class__ = cls          # reuse this request's socket and parsed headers
        getattr(self, f"do_{self.command}")()
        return True

    def translate_path(self, path):
        if path.startswith("/dev-fixtures/"):
            return str(FIXTURES / path.split("?", 1)[0].removeprefix("/dev-fixtures/"))
        return super().translate_path(path)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._api()
        self.send_error(405)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + fmt % args + "\n")


mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else 8000
    if FAKE:  # offline: fictional sources and a scripted model behind the real API code
        import os
        import tempfile
        os.environ.setdefault("GEMINI_API_KEY", "fake")
        os.environ.setdefault("FINN_CACHE_DIR", tempfile.mkdtemp(prefix="finn-dev-"))
        sys.path.insert(0, str(ROOT / "dev"))
        import fakes
        import pipeline.run  # noqa: F401  (fakes.install patches it too)
        fakes.install(setattr)
        print("using fictional fake sources (--fake)")
    print(f"FINN dev server on http://localhost:{port}  (?fixtures for sample data)")
    ThreadingHTTPServer(("0.0.0.0", port), Dev).serve_forever()
