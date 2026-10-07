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

log = logging.getLogger("broker-bridge")

NAME = "angel"
REQUIRED_ENV = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET"]

TOKEN_TO_ID = {"99926000": "NIFTY", "99926009": "BANKNIFTY", "99919000": "SENSEX"}


def run_forever(on_tick):
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
                sws.subscribe("broker-bridge", SmartWebSocketV2.LTP_MODE, [
                    {"exchangeType": 1, "tokens": ["99926000", "99926009"]},
                    {"exchangeType": 3, "tokens": ["99919000"]},
                ])
                log.info("[angel] subscribed (LTP)")

            def _on_data(_w, message):
                try:
                    if isinstance(message, dict) and message.get("subscription_mode") == 1:
                        sid = TOKEN_TO_ID.get(str(message.get("token")))
                        px = message.get("last_traded_price")
                        if sid and px is not None:
                            on_tick(sid, float(px) / 100.0)  # paise -> rupees
                except Exception as e:
                    log.warning("[angel] bad tick ignored: %s", e)

            sws.on_open = _on_open
            sws.on_data = _on_data
            sws.on_error = lambda _w, e: log.warning("[angel] ws error: %s", str(e)[:150])
            sws.on_close = lambda _w: log.warning("[angel] ws closed")
            sws.connect()  # blocks until the socket closes
        except KeyError as e:
            log.error("[angel] missing env var %s", e)
            time.sleep(60)
        except Exception as e:
            log.warning("[angel] retry in 15s: %s", str(e)[:200])
            time.sleep(15)
