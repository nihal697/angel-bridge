"""Upstox v2 adapter (REST polling). Status: BUILT FROM DOCS, NEEDS LIVE TEST.

- LTP endpoint shape per Upstox v2 docs:
  GET /v2/market-quote/ltp?instrument_key=NSE_INDEX|Nifty 50
  with `Authorization: Bearer <access token>`.
- Instrument keys follow Upstox's canonical `EXCHANGE|SYMBOL` format.
- AUTH REALITY: Upstox tokens come from an OAuth browser login and last ~a
  day. Refresh in the Upstox developer portal, update UPSTOX_ACCESS_TOKEN on
  Render (restarts the service). Failures are reported, never silent.
Env: UPSTOX_ACCESS_TOKEN.
"""

import logging

import requests

from .base import env, poll_forever

log = logging.getLogger("broker-bridge")

NAME = "upstox"
REQUIRED_ENV = ["UPSTOX_ACCESS_TOKEN"]

INSTRUMENTS = {"NSE_INDEX|Nifty 50": "NIFTY", "NSE_INDEX|Nifty Bank": "BANKNIFTY",
               "BSE_INDEX|SENSEX": "SENSEX"}
BASE = "https://api.upstox.com/v2"


def fetch_all():
    out = {}
    headers = {"Authorization": f"Bearer {env('UPSTOX_ACCESS_TOKEN')}", "Accept": "application/json"}
    for key, sid in INSTRUMENTS.items():
        r = requests.get(f"{BASE}/market-quote/ltp", headers=headers,
                         params={"instrument_key": key}, timeout=10)
        if r.status_code == 401:
            raise RuntimeError("upstox token rejected (401) — refresh it in the developer portal")
        r.raise_for_status()
        node = (r.json().get("data") or {}).get(key, {})
        px = node.get("last_price")
        if px is not None:
            out[sid] = float(px)
        else:
            log.warning("[upstox] no last_price for %s; keys=%s", key, list(node.keys()))
    return out


def run_forever(on_tick):
    log.info("[upstox] polling LTP (token is daily — refresh via developer portal)")
    poll_forever(NAME, fetch_all, on_tick)
