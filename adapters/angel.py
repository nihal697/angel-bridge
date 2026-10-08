"""Angel One SmartAPI adapter (WebSocket push). Status: LIVE-TESTED.

Tokens verified against Angel's live instrument master; login + subscribe +
tick parsing proven against the real API (see repo history).
Env: ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PASSWORD, ANGEL_TOTP_SECRET.
"""

import logging
import time

from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import pyotp

from .base import env

import optionchain
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def _exchange_ts(message):
    """Exchange event time from the tick itself; None if absent/invalid."""
    try:
        ms = int(message.get("exchange_timestamp") or 0)
        if ms > 0:
            return datetime.fromtimestamp(ms / 1000, tz=IST).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None

log = logging.getLogger("broker-bridge")

NAME = "angel"
REQUIRED_ENV = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET"]

TOKEN_TO_ID = {"99926000": "NIFTY", "99926009": "BANKNIFTY", "99919000": "SENSEX"}

# Option legs: {exchangeType: [tokens]}, refreshed by bridge.py as spot moves.
# token -> True membership for fast routing in on_data.
_option_tokens = {}
_option_set = set()
_live_sws = None


def set_option_tokens(mapping):
    """Replace the option subscription set; swaps live if connected."""
    global _option_tokens, _option_set
    _option_tokens = {int(k): [str(t) for t in v] for k, v in mapping.items() if v}
    _option_set = {t for v in _option_tokens.values() for t in v}
    sws = _live_sws
    if sws is not None:
        try:
            old = getattr(sws, "_opt_subscribed", {})
            for et, toks in old.items():
                if set(toks) - set(_option_tokens.get(et, [])):
                    sws.unsubscribe("broker-bridge", SmartWebSocketV2.LTP_MODE,
                                    [{"exchangeType": et, "tokens": list(set(toks) - set(_option_tokens.get(et, [])))}])
            new = [{"exchangeType": et, "tokens": toks} for et, toks in _option_tokens.items() if toks]
            if new:
                sws.subscribe("broker-bridge", SmartWebSocketV2.LTP_MODE, new)
            sws._opt_subscribed = {et: list(toks) for et, toks in _option_tokens.items()}
            log.info("[angel] option subscription now %d tokens", len(_option_set))
        except Exception as e:
            log.warning("[angel] live option resubscribe failed (picked up on reconnect): %s", str(e)[:150])


def current_option_tokens():
    """Currently subscribed option tokens, for the OI poller."""
    return {et: list(toks) for et, toks in _option_tokens.items() if toks}


def run_forever(on_tick):
    global _live_sws
    api_key, client_code = env("ANGEL_API_KEY"), env("ANGEL_CLIENT_CODE")
    while True:
        try:
            smart = SmartConnect(api_key)
            totp = pyotp.TOTP(env("ANGEL_TOTP_SECRET")).now()
            data = smart.generateSession(client_code, env("ANGEL_PASSWORD"), totp)
            if not data.get("status"):
                raise RuntimeError(f"login failed: {data}")
            feed_token = smart.getfeedToken()
            log.info("[angel] login OK")

            sws = SmartWebSocketV2(data["data"]["jwtToken"], api_key, client_code, feed_token)

            def _on_open(_w):
                global _live_sws
                _live_sws = sws
                sws.subscribe("broker-bridge", SmartWebSocketV2.LTP_MODE, [
                    {"exchangeType": 1, "tokens": ["99926000", "99926009"]},
                    {"exchangeType": 3, "tokens": ["99919000"]},
                ])
                new = [{"exchangeType": et, "tokens": toks} for et, toks in _option_tokens.items() if toks]
                if new:
                    sws.subscribe("broker-bridge", SmartWebSocketV2.LTP_MODE, new)
                sws._opt_subscribed = {et: list(toks) for et, toks in _option_tokens.items()}
                log.info("[angel] subscribed (LTP); options: %d tokens", len(_option_set))

            def _on_data(_w, message):
                try:
                    if isinstance(message, dict) and message.get("subscription_mode") == 1:
                        tok = str(message.get("token"))
                        px = message.get("last_traded_price")
                        if px is None:
                            return
                        price = float(px) / 100.0  # paise -> rupees
                        ts = _exchange_ts(message)
                        sid = TOKEN_TO_ID.get(tok)
                        if sid:
                            on_tick(sid, price, ts)
                        elif tok in _option_set:
                            optionchain.record_tick(tok, price, ts)
                except Exception as e:
                    log.warning("[angel] bad tick ignored: %s", e)

            sws.on_open = _on_open
            sws.on_data = _on_data
            sws.on_error = lambda _w, e: log.warning("[angel] ws error: %s", str(e)[:150])
            sws.on_close = lambda _w: log.warning("[angel] ws closed")
            sws.connect()  # blocks until the socket closes
            _live_sws = None
        except KeyError as e:
            log.error("[angel] missing env var %s", e)
            time.sleep(60)
        except Exception as e:
            log.warning("[angel] retry in 15s: %s", str(e)[:200])
            time.sleep(15)
