"""POST /api/ledger_step — read ONE earnings-call transcript into the ledger.

Body: {"state": <ledger state or null>, "symbol", "name", "quarter", "url"}
The browser calls this once per transcript, oldest first, so the investor
watches the ledger fill in. Each transcript is read by the cheap model once,
ever (cached by URL and the promises already open)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finn import ledger  # noqa: E402
from finn.sources import screener  # noqa: E402
from finn.sources.exchanges import download_attachment  # noqa: E402
from finn.web import ApiError, make_handler, symbol  # noqa: E402

_listed: dict[str, tuple[float, set]] = {}


def listed_transcripts(sym: str) -> set:
    """The server only fetches transcript URLs screener.in lists for this company,
    never an arbitrary URL from the browser. Memoised per warm instance."""
    hit = _listed.get(sym)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    urls = {t["url"] for t in screener.fetch_company(sym)["transcripts"]}
    _listed[sym] = (time.time(), urls)
    return urls


def post(body):
    sym = symbol(body.get("symbol"))
    url, quarter = body.get("url"), body.get("quarter")
    if not url or not str(url).startswith("https://") or not quarter:
        raise ApiError(400, "Need a transcript url and quarter.")
    if url not in listed_transcripts(sym):
        raise ApiError(400, "That transcript is not listed for this company.")
    state = body.get("state") or ledger.new_state(sym, body.get("name") or sym)
    if state.get("symbol") != sym:
        raise ApiError(400, "State belongs to a different company.")
    state = ledger.read_call(state, quarter, url, download_attachment)
    new = [p for p in state["promises"] if p["made_in"] == quarter]
    return {"state": state, "found": len(new),
            "updated": sum(1 for p in state["promises"] for e in p["history"]
                           if e["quarter"] == quarter and e["kind"] != "not_mentioned")}


handler = make_handler(post=post)
