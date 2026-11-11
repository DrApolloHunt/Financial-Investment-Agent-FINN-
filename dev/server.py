"""Local dev server: the same WSGI app Vercel runs, plus fictional fixtures.

    python dev/server.py [port] [--fake]
Open http://localhost:8000            (real data in public/data)
     http://localhost:8000/?fixtures  (fictional sample data from dev/fixtures)
--fake swaps every data source and the model for fictional fakes (offline).
"""
import os
import sys
import tempfile
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "dev" / "fixtures"
FAKE = "--fake" in sys.argv

if FAKE:
    os.environ.setdefault("GEMINI_API_KEY", "fake")
    os.environ.setdefault("FINN_CACHE_DIR", tempfile.mkdtemp(prefix="finn-dev-"))

from finn import web  # noqa: E402


def dev_app(environ, start_response):
    path = environ.get("PATH_INFO") or "/"
    if path.startswith("/dev-fixtures/"):
        target = (FIXTURES / path.removeprefix("/dev-fixtures/")).resolve()
        if FIXTURES.resolve() in target.parents and target.is_file():
            return web._respond(start_response, 200, target.read_bytes(), "application/json; charset=utf-8")
        return web._respond(start_response, 404, b"Not found", "text/plain")
    environ["PATH_INFO"] = path
    return web.app(environ, start_response)


class Threaded(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Quiet(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  " + fmt % args + "\n")


def install_fakes():
    sys.path.insert(0, str(ROOT / "dev"))
    import fakes
    import pipeline.run  # noqa: F401  (fakes.install patches it too)
    fakes.install(setattr)
    print("using fictional fake sources (--fake)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else 8000
    if FAKE:
        install_fakes()
    print(f"FINN dev server on http://localhost:{port}  (?fixtures for sample data)")
    make_server("0.0.0.0", port, dev_app, server_class=Threaded, handler_class=Quiet).serve_forever()
