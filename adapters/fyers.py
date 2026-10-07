"""FYERS adapter (REST polling). Status: BUILT FROM OFFICIAL SAMPLES.

- Index symbols + WS conventions per FyersDev/fyers-api-sample-code
  (NSE:NIFTY50-INDEX, NSE:NIFTYBANK-INDEX confirmed there; BSE:SENSEX-INDEX
  follows the identical convention).
- Quotes via the official fyers-apiv3 client (response: d[].v.lp).
- AUTH REALITY: FYERS access tokens are issued via a browser login and last
  ~a day. There is no fully-automatic refresh: regenerate the token in the
  FYERS portal, update FYERS_ACCESS_TOKEN on Render (restarts the service),
  done. The adapter reports auth failures plainly instead of dying quietly.
Env: FYERS_APP_ID, FYERS_ACCESS_TOKEN (as "appid:token" — exactly what the
portal shows; the client splits it).
"""

import logging

from .base import env, poll_forever

log = logging.getLogger("broker-bridge")

NAME = "fyers"
REQUIRED_ENV = ["FYERS_APP_ID", "FYERS_ACCESS_TOKEN"]

SYMBOLS = {"NSE:NIFTY50-INDEX": "NIFTY", "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
           "BSE:SENSEX-INDEX": "SENSEX"}

_client = None


def _client_or_raise():
    global _client
    if _client is None:
        from fyers_apiv3 import fyersModel
        token = env("FYERS_ACCESS_TOKEN")
        appid = token.split(":")[0] if ":" in token else env("FYERS_APP_ID")
        _client = fyersModel.FyersModel(client_id=appid, token=token, is_async=False, log_path="")
    return _client


def fetch_all():
    fyers = _client_or_raise()
    resp = fyers.quotes(data={"symbols": ",".join(SYMBOLS)})
    if not isinstance(resp, dict) or resp.get("s") not in ("ok", "Ok", "OK"):
        raise RuntimeError(f"fyers quotes rejected: {str(resp)[:200]}")
    out = {}
    for row in resp.get("d", []) or []:
        sid = SYMBOLS.get(row.get("n"))
        v = row.get("v") or {}
        px = v.get("lp")
        if sid and px is not None:
            try:
                out[sid] = float(px)
            except (TypeError, ValueError):
                pass
    if not out:
        log.warning("[fyers] empty result; row keys were: %s",
                    [list(r.keys()) for r in (resp.get("d") or [])[:1]])
    return out


def run_forever(on_tick):
    log.info("[fyers] polling quotes (token is daily — refresh via FYERS portal)")
    poll_forever(NAME, fetch_all, on_tick)
