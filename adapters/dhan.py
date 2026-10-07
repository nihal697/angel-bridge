"""DhanHQ adapter (REST polling). Status: BUILT FROM DOCS + LIVE MASTER.

- LTP endpoint + response shape per DhanHQ v2 docs (POST /v2/marketfeed/ltp).
- Index IDs (IDX_I 13/25/51) read from Dhan's live instrument master CSV.
- Auth is a STATIC token (Dhan web → API access): no daily re-login, ever.
Env: DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID.
"""

import logging

import requests

from .base import env, poll_forever

log = logging.getLogger("broker-bridge")

NAME = "dhan"
REQUIRED_ENV = ["DHAN_ACCESS_TOKEN", "DHAN_CLIENT_ID"]

INSTRUMENTS = {"IDX_I": ["13", "25", "51"]}  # Nifty 50, Bank Nifty, Sensex
ID_TO_SYMBOL = {"13": "NIFTY", "25": "BANKNIFTY", "51": "SENSEX"}
BASE = "https://api.dhan.co/v2"


def _headers():
    return {"access-token": env("DHAN_ACCESS_TOKEN"), "client-id": env("DHAN_CLIENT_ID"),
            "Content-Type": "application/json", "Accept": "application/json"}


def fetch_all():
    r = requests.post(f"{BASE}/marketfeed/ltp", headers=_headers(),
                      json=INSTRUMENTS, timeout=10)
    r.raise_for_status()
    data = (r.json().get("data") or {}).get("IDX_I", {})
    out = {}
    for sid, v in data.items():
        px = (v or {}).get("last_price")
        if px is not None and ID_TO_SYMBOL.get(str(sid)):
            out[ID_TO_SYMBOL[str(sid)]] = float(px)
    if not out:
        log.warning("[dhan] empty result; top-level keys were: %s", list((r.json().get("data") or {}).keys()))
    return out


def run_forever(on_tick):
    log.info("[dhan] polling LTP (static token, no re-login needed)")
    poll_forever(NAME, fetch_all, on_tick)
