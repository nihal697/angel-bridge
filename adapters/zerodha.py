"""Zerodha Kite adapter (REST polling). Status: BUILT FROM LIVE DUMP, NEEDS LIVE TEST.

- Index tokens read from Kite's live instrument dump (api.kite.trade):
  NSE 256265 = NIFTY 50, NSE 260105 = NIFTY BANK, BSE 265 = SENSEX.
  These index tokens are long-stable (unlike weekly F&O tokens).
- Quote via the official kiteconnect client: kite.quote(["NSE:NIFTY 50", ...])
  returns {"NSE:NIFTY 50": {"last_price": ...}}.
- COST + AUTH REALITY: Kite Connect API costs ~Rs 2,000/month AND its access
  token needs a daily browser login (request_token flow). This adapter is for
  completeness — for this use-case Angel/Dhan/Shoonya are free and better.
Env: ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN (daily).
"""

import logging

from .base import env, poll_forever

log = logging.getLogger("broker-bridge")

NAME = "zerodha"
REQUIRED_ENV = ["ZERODHA_API_KEY", "ZERODHA_ACCESS_TOKEN"]

INSTRUMENTS = {"NSE:NIFTY 50": "NIFTY", "NSE:NIFTY BANK": "BANKNIFTY", "BSE:SENSEX": "SENSEX"}

_kite = None


def _kite_or_raise():
    global _kite
    if _kite is None:
        from kiteconnect import KiteConnect
        _kite = KiteConnect(api_key=env("ZERODHA_API_KEY"))
        _kite.set_access_token(env("ZERODHA_ACCESS_TOKEN"))
    return _kite


def fetch_all():
    kite = _kite_or_raise()
    try:
        data = kite.quote(list(INSTRUMENTS))
    except Exception as e:
        if "403" in str(e) or "token" in str(e).lower():
            raise RuntimeError(f"kite token rejected — refresh it (daily): {e}")
        raise
    out = {}
    for key, sid in INSTRUMENTS.items():
        px = (data.get(key) or {}).get("last_price")
        if px is not None:
            out[sid] = float(px)
    return out


def run_forever(on_tick):
    log.info("[zerodha] polling quotes (paid API + daily token — see module docstring)")
    poll_forever(NAME, fetch_all, on_tick)
