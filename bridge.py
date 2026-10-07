"""
Personal Angel One SmartAPI bridge — live NSE/BSE index LTP over plain HTTP.

Serves ONLY the 3 indices (Nifty 50, Nifty Bank, Sensex) for personal
paper-trading use. No order placement, no data redistribution.

Design notes (read before modifying):
- Angel sessions die roughly daily, and sockets drop. The worker loop below
  simply re-logs-in and reconnects forever — no silent death.
- Prices on the V2 LTP feed arrive in paise; we expose rupees.
- Outside 09:15–15:30 IST (Mon–Fri) there are no ticks; /ltp returns the
  last cached values flagged stale:true instead of pretending to be live.
- Credentials come ONLY from environment variables. Never commit them.
"""

import logging
import os
import threading
import time
from datetime import datetime, time as dtime, timezone, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import pyotp

log = logging.getLogger("angel-bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

# Tokens verified against Angel's live instrument master (OpenAPIScripMaster).
SYMBOLS = [
    {"id": "NIFTY",     "exchange": "NSE", "exchangeType": 1, "token": "99926000"},
    {"id": "BANKNIFTY", "exchange": "NSE", "exchangeType": 1, "token": "99926009"},
    {"id": "SENSEX",    "exchange": "BSE", "exchangeType": 3, "token": "99919000"},
]
TOKEN_TO_ID = {s["token"]: s["id"] for s in SYMBOLS}

latest = {s["id"]: {"price": None, "ts": None} for s in SYMBOLS}
state = {"connected": False, "last_login": None, "last_tick_at": None, "error": None}


def market_is_open(now=None):
    now = now or datetime.now(IST)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def angel_login():
    """Fresh login. Returns (jwt, feed_token). Raises RuntimeError on failure."""
    api_key = os.environ["ANGEL_API_KEY"]
    client_code = os.environ["ANGEL_CLIENT_CODE"]
    password = os.environ["ANGEL_PASSWORD"]
    totp = pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now()

    smart = SmartConnect(api_key)
    data = smart.generateSession(client_code, password, totp)
    if not data.get("status"):
        raise RuntimeError(f"Angel login failed: {data}")
    feed_token = smart.getfeedToken()
    state["last_login"] = datetime.now(IST).isoformat()
    state["error"] = None
    log.info("Angel login OK")
    return data["data"]["jwtToken"], feed_token


def on_data(_wsapp, message):
    try:
        if isinstance(message, dict) and message.get("subscription_mode") == 1:
            sid = TOKEN_TO_ID.get(str(message.get("token")))
            if sid and message.get("last_traded_price") is not None:
                price = float(message["last_traded_price"]) / 100.0  # paise -> rupees
                ts = datetime.now(IST).isoformat()
                latest[sid] = {"price": price, "ts": ts}
                state["last_tick_at"] = ts
    except Exception as e:  # never let a bad tick kill the socket
        log.warning("bad tick ignored: %s", e)


def _on_open(sws):
    sws.subscribe("angel-bridge", SmartWebSocketV2.LTP_MODE, [
        {"exchangeType": 1, "tokens": ["99926000", "99926009"]},  # NSE: Nifty, BankNifty
        {"exchangeType": 3, "tokens": ["99919000"]},              # BSE: Sensex
    ])
    state["connected"] = True
    log.info("subscribed to 3 indices (LTP)")


def run_feed_forever():
    """Login -> subscribe -> block on socket -> on any exit, wait and redo."""
    api_key = os.environ["ANGEL_API_KEY"]
    client_code = os.environ["ANGEL_CLIENT_CODE"]
    while True:
        try:
            jwt, feed_token = angel_login()
            sws = SmartWebSocketV2(jwt, api_key, client_code, feed_token)
            sws.on_open = lambda wsapp: _on_open(sws)
            sws.on_data = on_data
            sws.on_error = lambda _w, e: log.warning("ws error: %s", e)
            sws.on_close = lambda _w: log.warning("ws closed")
            sws.connect()  # blocks until the socket closes
        except KeyError as e:
            state["error"] = f"missing env var: {e} — set ANGEL_API_KEY/CLIENT_CODE/PASSWORD/TOTP_SECRET"
            log.error(state["error"])
            time.sleep(60)
        except Exception as e:
            state["connected"] = False
            state["error"] = str(e)[:300]
            log.warning("feed loop retry in 15s: %s", state["error"])
            time.sleep(15)
        finally:
            state["connected"] = False


app = FastAPI(title="angel-bridge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])


@app.on_event("startup")
def startup():
    threading.Thread(target=run_feed_forever, daemon=True).start()


@app.get("/")
def root():
    return {"service": "angel-bridge", "symbols": [s["id"] for s in SYMBOLS], "try": "/ltp"}


@app.get("/health")
def health():
    return {"connected": state["connected"], "market_open": market_is_open(),
            "last_login": state["last_login"], "last_tick_at": state["last_tick_at"],
            "error": state["error"]}


@app.get("/ltp")
def ltp():
    open_now = market_is_open()
    return {"as_of": datetime.now(IST).isoformat(), "market_open": open_now,
            "stale": not open_now,
            "data": {k: dict(v) for k, v in latest.items()}}
