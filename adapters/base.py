"""Broker adapter interface.

Every adapter serves the same 3 ids — NIFTY, BANKNIFTY, SENSEX — so the
HTTP contract (/ltp) never changes no matter which broker feeds it.

An adapter exposes:
  NAME: str                  human name, matches BROKER env value
  REQUIRED_ENV: list[str]    env vars it needs (read at runtime, never committed)
  run_forever(on_tick)       blocks forever; calls on_tick(id, price) on fresh
                             prices and handles its own login/refresh/reconnect.

Polling adapters get a free loop via poll_forever(); push adapters (Angel WS)
run their own loop. Nothing here ever throws out — log and retry instead.
"""

import logging
import os
import time
from typing import Callable

log = logging.getLogger("broker-bridge")

SYMBOL_IDS = ("NIFTY", "BANKNIFTY", "SENSEX")


def env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise KeyError(name)
    return val


def poll_forever(name: str, fetch, on_tick: Callable[[str, float], None]) -> None:
    """Call fetch() -> {id: price} every POLL_SECS; survives all errors."""
    interval = int(os.environ.get("POLL_SECS", "5"))
    while True:
        try:
            for sid, price in (fetch() or {}).items():
                if sid in SYMBOL_IDS and isinstance(price, (int, float)) and price > 0:
                    on_tick(sid, float(price))
        except KeyError as e:
            log.error("[%s] missing env var %s — set it and restart", name, e)
            time.sleep(60)
        except Exception as e:
            log.warning("[%s] fetch failed, retrying: %s", name, str(e)[:200])
            time.sleep(15)
            continue
        time.sleep(interval)
