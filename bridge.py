"""
broker-bridge — live Nifty/BankNifty/Sensex LTP over plain HTTP, any broker.

  BROKER=angel|dhan|shoonya|fyers|upstox|zerodha   (default: angel)

Every adapter serves the same 3 ids, so GET /ltp never changes shape and the
phone app needs zero updates when you switch brokers. Credentials come ONLY
from environment variables. Never commit them.
"""

import logging
import threading
from datetime import datetime, time as dtime, timezone, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adapters import angel, dhan, shoonya, fyers, upstox, zerodha
from adapters.base import SYMBOL_IDS
import optionchain
import upstox_chain
import os

log = logging.getLogger("broker-bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ADAPTERS = {m.NAME: m for m in (angel, dhan, shoonya, fyers, upstox, zerodha)}

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

latest = {sid: {"price": None, "ts": None} for sid in SYMBOL_IDS}
state = {"broker": None, "connected": False, "last_tick_at": None, "error": None}


def market_is_open(now=None):
    now = now or datetime.now(IST)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def on_tick(sid: str, price: float):
    if sid in latest and price and price > 0:
        latest[sid] = {"price": price, "ts": datetime.now(IST).isoformat()}
        state["last_tick_at"] = latest[sid]["ts"]
        state["connected"] = True
        state["error"] = None


def run_feed_forever():
    name = os.environ.get("BROKER", "angel").strip().lower()
    adapter = ADAPTERS.get(name)
    if adapter is None:
        state["error"] = f"unknown BROKER={name!r} — pick one of {sorted(ADAPTERS)}"
        log.error(state["error"])
        return
    state["broker"] = adapter.NAME
    log.info("using broker adapter: %s", adapter.NAME)
    adapter.run_forever(on_tick)  # blocks forever; adapters self-heal


app = FastAPI(title="broker-bridge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])


@app.on_event("startup")
def startup():
    threading.Thread(target=run_feed_forever, daemon=True).start()
    threading.Thread(target=_chain_bootstrap, daemon=True).start()


def _chain_bootstrap():
    """Master download + option subscription upkeep (Angel only for now)."""
    import time as _t
    try:
        optionchain.load_master()
    except Exception as e:
        log.warning("master download failed at startup (retrying in loop): %s", str(e)[:150])
    threading.Thread(target=optionchain.refresh_loop, daemon=True).start()
    while True:
        try:
            if os.environ.get("BROKER", "angel").strip().lower() == "angel" and optionchain.master_rows:
                _refresh_option_subs()
        except Exception as e:
            log.warning("option resubscribe failed: %s", str(e)[:150])
        _t.sleep(600)


def _refresh_option_subs():
    """Subscribe nearest-expiry ATM ±12 per underlying (Angel WS)."""
    mapping, S = {}, {}
    for uid, (_seg, _name, et) in optionchain.UNDERLYINGS.items():
        idx_id = {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY", "SENSEX": "SENSEX"}[uid]
        spot = (latest.get(idx_id) or {}).get("price")
        if not spot:
            continue
        S[uid] = spot
        exp = optionchain.nearest_expiry(uid)
        if not exp:
            continue
        rows = optionchain.chain_rows(uid, exp)
        strikes = sorted(rows)
        atm = min(strikes, key=lambda s: abs(s - spot))
        sel = [s for s in strikes if abs(s - atm) <= 12 * _step(strikes)]
        toks = []
        for s in sel:
            for side in ("CE", "PE"):
                t = (rows[s].get(side) or {}).get("token")
                if t:
                    toks.append(t)
        mapping.setdefault(et, []).extend(toks)
    if mapping:
        angel.set_option_tokens(mapping)
        log.info("option subs refreshed (spots=%s)",
                 {k: round(v, 1) for k, v in S.items()})


def _step(strikes):
    strikes = sorted(strikes)
    diffs = [b - a for a, b in zip(strikes, strikes[1:]) if b - a > 0]
    return min(diffs) if diffs else 50


@app.get("/")
def root():
    return {"service": "broker-bridge", "brokers": sorted(ADAPTERS),
            "symbols": list(SYMBOL_IDS), "try": "/ltp"}


@app.get("/health")
def health():
    return {"broker": state["broker"], "connected": state["connected"],
            "market_open": market_is_open(), "last_tick_at": state["last_tick_at"],
            "error": state["error"]}


@app.get("/ltp")
def ltp():
    open_now = market_is_open()
    return {"as_of": datetime.now(IST).isoformat(), "market_open": open_now,
            "broker": state["broker"], "stale": not open_now,
            "data": {k: dict(v) for k, v in latest.items()}}


@app.get("/optionchain/expiries")
def option_expiries(underlying: str = "NIFTY", source: str = "angel"):
    underlying = underlying.strip().upper()
    if underlying not in optionchain.UNDERLYINGS:
        return {"error": f"unknown underlying {underlying!r} — use NIFTY, BANKNIFTY or SENSEX"}
    source = source.strip().lower()
    if source == "upstox":
        try:
            return {"underlying": underlying, "source": "upstox",
                    "expiries": upstox_chain.expiries(underlying)}
        except upstox_chain.UpstoxAuthError as e:
            return {"error": str(e)}
        except Exception as e:
            log.warning("/optionchain/expiries failed: %s", str(e)[:200])
            return {"error": "upstox call failed — check bridge logs"}
    if not optionchain.master_rows:
        return {"error": "instrument master not loaded yet — retry in a minute"}
    return {"underlying": underlying, "source": "angel",
            "expiries": optionchain.expiries(underlying)}


@app.get("/optionchain")
def option_chain(underlying: str = "NIFTY", expiry: str = "current_week",
                 source: str = "angel"):
    underlying = underlying.strip().upper()
    if underlying not in optionchain.UNDERLYINGS:
        return {"error": f"unknown underlying {underlying!r} — use NIFTY, BANKNIFTY or SENSEX"}
    source = source.strip().lower()
    if source == "upstox":
        try:
            out = upstox_chain.chain(underlying, expiry.strip() or "current_week")
            out["source"] = "upstox"
            return out
        except upstox_chain.UpstoxAuthError as e:
            return {"error": str(e)}
        except Exception as e:
            log.warning("/optionchain failed: %s", str(e)[:200])
            return {"error": "upstox call failed — check bridge logs"}
    # Angel master + WS ticks. Greeks/OI are null here (Angel publishes no
    # chain endpoint) — ltp/lot/expiry/strike are first-party and exact.
    if not optionchain.master_rows:
        return {"error": "instrument master not loaded yet — retry in a minute"}
    idx_id = {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY", "SENSEX": "SENSEX"}[underlying]
    spot = (latest.get(idx_id) or {}).get("price")
    exp = expiry.strip()
    if exp in ("", "nearest", "current_week"):
        exp = optionchain.nearest_expiry(underlying)
    out = optionchain.chain(underlying, exp, spot)
    out["source"] = "angel"
    return out
