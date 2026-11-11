"""Vercel entrypoint (Python preset).

One WSGI app serves the research API at /api/*. Static files in public/ are
served by Vercel's CDN; the app also serves them itself as a fallback.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from finn.web import app  # noqa: E402,F401  (Vercel looks for a variable named `app`)
