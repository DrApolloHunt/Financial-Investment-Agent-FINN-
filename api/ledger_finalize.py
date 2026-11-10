"""POST /api/ledger_finalize — statuses (rules) + verdicts (one reasoning call).

Body: {"state": <ledger state>, "quarters": <quarterly table>, "latest": "Q2 FY27"}"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finn import ledger  # noqa: E402
from finn.web import ApiError, make_handler  # noqa: E402


def post(body):
    state = body.get("state")
    if not state or "promises" not in state:
        raise ApiError(400, "Need a ledger state.")
    return ledger.finalize(state, body.get("quarters") or {}, body.get("latest"), use_model=True)


handler = make_handler(post=post)
